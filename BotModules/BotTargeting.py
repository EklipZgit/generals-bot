import math
import time

import BotModules as BM
import typing

import ExpandUtils
import logbook

import SearchUtils
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotComms import BotComms

from Models import ContestData
from MapMatrix import TileSet, MapMatrix, MapMatrixInterface
from Path import Path
from ViewInfo import PathColorer, TargetStyle
from base.client.map import Tile, MapBase
from Models.Move import Move

class BotTargeting:
    @staticmethod
    def get_afk_players(bot) -> typing.List:
        if bot._afk_players is None:
            bot._afk_players = []
            minTilesToNotBeAfk = math.sqrt(bot._map.turn)
            for player in bot._map.players:
                if player.index == bot.general.player:
                    continue
                if (player.leftGame or (bot._map.turn >= 50 and player.tileCount <= minTilesToNotBeAfk)) and not player.dead:
                    bot._afk_players.append(player)
                    logbook.info(f"player {bot._map.usernames[player.index]} ({player.index}) was afk")

        return bot._afk_players

    @staticmethod
    def check_target_player_just_took_city(bot):
        if bot.targetPlayerObj is not None and bot.targetPlayer != -1:
            teamData = bot.opponent_tracker.get_current_team_scores_by_player(bot.targetPlayer)
            numLivingPlayers = len(teamData.livingPlayers)
            if teamData.cityCount > bot._lastTargetPlayerCityCount:
                bot.viewInfo.add_info_line('Dropping timings because target player just took a city.')

                if bot._map.is_2v2:
                    mostRecentCity = None
                    for en in bot.opponent_tracker.get_team_players_by_player(bot.targetPlayer):
                        for city in bot._map.players[en].cities:
                            if city.delta.oldOwner != city.player:
                                mostRecentCity = city

                    if mostRecentCity is None:
                        mostRecentCity = bot.targetPlayerExpectedGeneralLocation

                    BotComms.send_teammate_communication(bot, f'Opps have {teamData.cityCount - numLivingPlayers} cities. New city might be around here:', mostRecentCity)

                bot.timings = None

            bot._lastTargetPlayerCityCount = teamData.cityCount

    @staticmethod
    def get_2v2_launch_point(bot) -> Tile:
        fromTile = bot.general
        usDist = BotPathingUtils.distance_from_general(bot, bot.targetPlayerExpectedGeneralLocation)
        allyAttackPath = BotPathingUtils.get_path_to_target(
            bot,
            bot.targetPlayerExpectedGeneralLocation,
            preferEnemy=True,
            preferNeutral=True,
            fromTile=bot.teammate_general
        )
        if allyAttackPath is None:
            return bot.general
        allyDist = allyAttackPath.length
        lockGeneral = False

        teammateDistFromUs = bot.teammate_path.length

        teammateRallyDistOffset = teammateDistFromUs // 4

        if bot.targetPlayerObj.knowsAllyKingLocation and bot.targetPlayerObj.knowsKingLocation:
            fromTile = bot.teammate_path.get_subsegment(2 * bot.teammate_path.length // 5).tail.tile
            teammateRallyDistOffset = teammateDistFromUs // 2
            lockGeneral = False
        elif bot.targetPlayerObj.knowsAllyKingLocation:
            fromTile = bot.teammate_general
            lockGeneral = True
            bot.viewInfo.add_info_line(
                f'ALLY lp {str(fromTile)} due to vision')
        elif bot.targetPlayerObj.knowsKingLocation:
            fromTile = bot.general
            lockGeneral = True
            bot.viewInfo.add_info_line(
                f'SELF lp {str(fromTile)} due to vision')

        if teammateDistFromUs < 15 and not lockGeneral:
            contested = BotTargeting.get_contested_targets(bot)
            if len(contested) > 0:
                fromTile = contested[0].tile
                bot.launchPoints = [c.tile for c in contested]
            elif allyDist + teammateRallyDistOffset <= usDist:
                fromTile = bot.teammate_general
                bot.viewInfo.add_info_line(
                    f'Ally lp {str(bot.teammate_general)} dist {allyDist} from {str(bot.targetPlayerExpectedGeneralLocation)} vs us {usDist}')

        return fromTile

    @staticmethod
    def are_more_teams_alive_than(bot, numTeams: int) -> bool:
        aliveTeams = set()
        afkPlayers = BotTargeting.get_afk_players(bot)
        teams = MapBase.get_teams_array(bot._map)

        for player in bot._map.players:
            if not player.dead and player.tileCount > 3 and player not in afkPlayers:
                aliveTeams.add(teams[player.index])

        if len(aliveTeams) > numTeams:
            return True

        return False

    @staticmethod
    def getDistToEnemy(bot, tile):
        dist = 1000
        for i in range(len(bot._map.generals)):
            gen = bot._map.generals[i]
            genDist = 0
            if gen is not None:
                genDist = bot._map.euclidDist(gen.x, gen.y, tile.x, tile.y)
            elif bot.generalApproximations[i][2] > 0:
                genDist = bot._map.euclidDist(bot.generalApproximations[i][0], bot.generalApproximations[i][1], tile.x, tile.y)

            if genDist < dist:
                dist = genDist
        return dist

    @staticmethod
    def get_safe_per_tile_bfs_depth(bot):
        depth = 9
        if bot._map.rows * bot._map.cols > 4000:
            depth = 1
        elif bot._map.rows * bot._map.cols > 2000:
            depth = 2
        elif bot._map.rows * bot._map.cols > 1500:
            depth = 3
        elif bot._map.rows * bot._map.cols > 1100:
            depth = 4
        elif bot._map.rows * bot._map.cols > 500:
            depth = 5
        elif bot._map.rows * bot._map.cols > 350:
            depth = 7
        return depth

    @staticmethod
    def get_target_player_possible_general_location_tiles_sorted(
            bot,
            elimNearbyRange: int = 2,
            player: int = -2,
            cutoffEmergenceRatio: float = 0.333,
            includeCities: bool = False,
            limitNearbyTileRange: int = -1
    ) -> typing.List[Tile]:
        """

        @param elimNearbyRange: Drops tiles that are within this many tiles from a tile that is already included. Basically forces the resulting list to not just be a gradient clustered around the one highest emergence point.
        @param player:
        @param cutoffEmergenceRatio:
        @return:
        """

        if player == -2:
            player = bot.targetPlayer

        if player == -1:
            return []

        if bot._map.players[player].general is not None:
            return [bot._map.players[player].general]

        emergenceVal = 0
        if player == bot.targetPlayer:
            emergenceVal = bot.armyTracker.emergenceLocationMap[player][bot.targetPlayerExpectedGeneralLocation]

        emergenceCutoff = int(emergenceVal * cutoffEmergenceRatio)

        connectedDistances = None
        if len(bot.armyTracker.connectedByPlayer[player]) > 0:
            connectedDistances = SearchUtils.build_distance_map_matrix(bot._map, bot.armyTracker.connectedByPlayer[player])

        emergenceVals = []
        for tile in bot._map.get_all_tiles():
            if not tile.discovered:
                emergenceAmt = bot.armyTracker.get_tile_emergence_for_player(tile, player)
                if not tile.isObstacle and bot.armyTracker.valid_general_positions_by_player[player][tile]:
                    if emergenceAmt > emergenceCutoff:
                        emergenceVals.append((emergenceAmt, tile))
                elif includeCities and tile.isUndiscoveredObstacle and emergenceAmt > 0:
                    if emergenceAmt > emergenceCutoff:
                        emergenceVals.append((emergenceAmt, tile))

        if len(emergenceVals) == 0 and bot.undiscovered_priorities is not None:
            for tile in bot._map.get_all_tiles():
                if not tile.discovered and not tile.isObstacle and bot.armyTracker.valid_general_positions_by_player[player][tile]:
                    emergenceAmt = bot.undiscovered_priorities.raw[tile.tile_index]
                    emergenceAmt -= BotPathingUtils.get_distance_from_board_center(bot, tile, center_ratio=0.35) * 0.1
                    if connectedDistances is not None:
                        emergenceAmt += 30.0 / (connectedDistances.raw[tile.tile_index] + 3)
                    emergenceVals.append((emergenceAmt, tile))

        tilesSorted = [tile for val, tile in sorted(emergenceVals, reverse=True) if tile != bot.targetPlayerExpectedGeneralLocation]
        if player == bot.targetPlayer and bot.targetPlayerExpectedGeneralLocation is not None and bot.armyTracker.valid_general_positions_by_player[player].raw[bot.targetPlayerExpectedGeneralLocation.tile_index]:
            tilesSorted.insert(0, bot.targetPlayerExpectedGeneralLocation)

        elimSet = set()

        finalTiles = []
        retry = True
        while retry:
            retry = False
            for tile in tilesSorted:
                if tile.tile_index in elimSet:
                    continue
                if limitNearbyTileRange > 0 and bot.territories.territoryDistances[player].raw[tile.tile_index] > limitNearbyTileRange:
                    continue

                finalTiles.append(tile)
                if elimNearbyRange > 0:
                    SearchUtils.breadth_first_foreach_fast_no_neut_cities(bot._map, [tile], elimNearbyRange, lambda t: elimSet.add(t.tile_index))
            if len(finalTiles) == 0 and limitNearbyTileRange > 0:
                retry = True
                limitNearbyTileRange = -1

        return finalTiles

    @staticmethod
    def _get_furthest_apart_3_enemy_general_locations(bot, player) -> typing.Tuple[typing.List[Tile], MapMatrixInterface[int]]:
        valids = bot.armyTracker.valid_general_positions_by_player[player].raw

        furthests = []
        iterMm = SearchUtils.build_distance_map_matrix(bot._map, bot.player.tiles)
        rawDists = iterMm.raw
        while len(furthests) < 3:
            furthestValidDist = 0
            furthestValid: Tile | None = None
            for tile in bot._map.tiles_by_index:
                dist = rawDists[tile.tile_index]
                if dist <= furthestValidDist:
                    continue

                if valids[tile.tile_index]:
                    furthestValid = tile
                    furthestValidDist = dist

            if furthestValid is None:
                break

            SearchUtils.extend_distance_map_matrix(bot._map, [furthestValid], iterMm)
            furthests.append(furthestValid)
            bot.viewInfo.add_targeted_tile(furthestValid, TargetStyle.PURPLE, radiusReduction=-2)

        if len(furthests) == 0:
            bot.info(f'No furthests...?')
            return furthests, BotStateQueries.get_intergeneral_analysis(bot).bMap.copy()

        return furthests, SearchUtils.build_distance_map_matrix(bot._map, furthests)

    @staticmethod
    def is_ffa_situation(bot) -> bool:
        if bot._is_ffa_situation is None:
            bot._is_ffa_situation = not bot._map.is_walled_city_game and BotTargeting.are_more_teams_alive_than(bot, 2)

        return bot._is_ffa_situation

    @staticmethod
    def find_fog_bisection_targets(bot) -> typing.Set[Tile]:
        bisects = set()
        if bot.targetPlayer == -1:
            return bisects

        candidates, distances, bisectPaths = bot.armyTracker.find_territory_bisection_paths(bot.targetPlayer)

        for tile in bot._map.get_all_tiles():
            bot.viewInfo.bottomMidLeftGridText[tile] = f'{"b" if candidates[tile] else "n"}{distances[tile]}'

        for path in bisectPaths:
            bot.viewInfo.color_path(PathColorer(
                path,
                0,
                0,
                0,
                255,
                alphaMinimum=155
            ))

            tg = path.tail.tile

            bot.viewInfo.add_targeted_tile(tg, TargetStyle.TEAL)

            bisects.add(tg)
            logbook.info(f'BISECTS INCLUDES {str(tg)}!')

        return bisects

    @staticmethod
    def increment_attack_counts(bot, tile: Tile):
        contestData = bot.contest_data.get(tile, None)
        if contestData is None:
            contestData = ContestData(tile)
            bot.contest_data[tile] = contestData

        if contestData.last_attacked_turn < bot._map.turn - 5:
            contestData.attacked_count += 1

        contestData.last_attacked_turn = bot._map.turn

    @staticmethod
    def get_contested_targets(
            bot,
            shortTermContestCutoff: int = 25,
            longTermContestCutoff: int = 60,
            numToInclude=3,
            excludeGeneral: bool = False
    ) -> typing.List[ContestData]:
        contestedSorted = [c for c in sorted(bot.contest_data.values(), key=lambda c: c.last_attacked_turn, reverse=True) if not c.tile.isGeneral or not excludeGeneral]

        mostRecentTargets = [c for c in contestedSorted[0:numToInclude] if c.last_attacked_turn > bot._map.turn - longTermContestCutoff]

        if len(mostRecentTargets) == 0:
            return []

        shortTermTargets = [t for t in mostRecentTargets if t.last_attacked_turn > bot._map.turn - shortTermContestCutoff]
        if len(shortTermTargets) > 0:
            mostRecentTargets = shortTermTargets

        logbook.info(f'Found contested tiles in get_contested_targets: {mostRecentTargets}')

        return mostRecentTargets

    @staticmethod
    def get_median_tile_value(bot, percentagePoint=50, player: int = -1):
        if player == -1:
            player = bot.general.player

        tiles = [tile for tile in bot._map.players[player].tiles]
        tiles = sorted(tiles, key=lambda tile: tile.army)
        tileIdx = max(0, int(len(tiles) * percentagePoint // 100 - 1))
        if len(tiles) > tileIdx:
            return tiles[tileIdx].army
        else:
            logbook.info("whoah, dude cmon,Z ZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzzZZzz")
            logbook.info("hit that weird tileIdx bug.")
            return 0

    @staticmethod
    def find_enemy_city_path(bot, negativeTiles: TileSet, force: bool = False) -> typing.Tuple[int, Path | None]:
        scores = [c for c in BM.BotCityOps.BotCityOps.get_enemy_cities_by_priority(bot)]
        foundScores = [c for c in scores if not c.isTempFogPrediction or c.discovered]
        if len(foundScores) > 0:
            scores = foundScores

        approxed = 0
        tgTile = None
        maxDiff = -10000
        bestTurns = -1

        start = time.perf_counter()

        prevApproxed = bot.enemy_city_approxed_attacks
        bot.enemy_city_approxed_attacks = {}


        for tile in scores:
            preCalcedOffensePlan = bot.win_condition_analyzer.contestable_city_offense_plans.get(tile, None)
            if preCalcedOffensePlan is None:
                logbook.info(f'en city @{tile} skipped because win condition analyzer didnt think it was contestable.')
                continue

            if bot.territories.is_tile_in_friendly_territory(tile) or bot._map.is_player_on_team_with(bot.targetPlayer, tile.player):
                if approxed >= 2:
                    bot.viewInfo.add_stats_line(f'en city @{tile} approxed > 2')
                    break

                if not tile.discovered and tile.isTempFogPrediction:
                    bot.viewInfo.add_stats_line(f'en city @{tile} skipped, temp fog prediction')
                    continue

                if tile in prevApproxed and tile not in bot.city_capture_plan_tiles and not bot._map.is_army_bonus_turn:
                    bot.viewInfo.add_stats_line(f'en city @{tile} skipped, prevApproxed and not in plan')
                    continue

                approxed += 1

                if time.perf_counter() - start > 0.025:
                    bot.viewInfo.add_stats_line(f'OUT OF TIME city @{tile}')
                    continue

                timing = 30 - ((bot._map.turn + 5) % 50) % 10
                with bot.perf_timer.begin_move_event(f'en city @{tile} approx attack/def {timing}t'):
                    curLeft, ourAttack, theirDef = bot.win_condition_analyzer.get_dynamic_approximate_attack_defense(tile, negativeTiles, minTurns=4, maxTurns=timing)
                    bot.enemy_city_approxed_attacks[tile] = (curLeft, ourAttack, theirDef)

                diff = ourAttack - theirDef
                bot.viewInfo.add_stats_line(f'en city @{tile} in {curLeft} diff {diff} (us={ourAttack} vs them={theirDef})')

                if ourAttack > theirDef and maxDiff < diff:
                    logbook.info(f'Approx attack/def shows our attack {ourAttack}, their def {theirDef}')
                    tgTile = tile
                    maxDiff = diff
                    bestTurns = curLeft

        if tgTile is None:
            return bestTurns, None

        bestTurns = -1
        return bestTurns, BotPathingUtils.get_path_to_target(bot, tgTile)

    @staticmethod
    def get_path_to_target_player(bot, isAllIn=False, cutLength: int | None = None) -> Path | None:
        maxTile = bot.targetPlayerExpectedGeneralLocation
        if maxTile is None:
            return None

        if bot.targetPlayerExpectedGeneralLocation != maxTile and bot._map.turn > 50:
            BotComms.send_teammate_communication(bot, f"I will be targeting {bot._map.usernames[bot.targetPlayer]} over here.", maxTile, cooldown=50, detectOnMessageAlone=True)

        with bot.perf_timer.begin_move_event('rebuilding intergeneral_analysis'):
            bot.board_analysis.rebuild_intergeneral_analysis(bot.targetPlayerExpectedGeneralLocation, bot.armyTracker.valid_general_positions_by_player)

        if bot.teammate_path is not None:
            manhattanDist = abs(bot.teammate_general.x - bot.general.x) + abs(bot.teammate_general.y - bot.general.y)
            if manhattanDist > 11:
                bot.viewInfo.add_info_line(f'teammate path {bot.teammate_path.length}, mahattan {manhattanDist}')
                bot.viewInfo.color_path(PathColorer(
                    bot.teammate_path,
                    0, 0, 255
                ))

        enemyDistMap = None
        if bot.board_analysis is not None and bot.board_analysis.intergeneral_analysis is not None and bot.board_analysis.intergeneral_analysis.bMap is not None:
            enemyDistMap = BotStateQueries.get_intergeneral_analysis(bot).bMap.copy()
        else:
            logbook.info('building distmap after rebuilding intergen analysis')
            enemyDistMap = bot._map.distance_mapper.get_tile_dist_matrix(bot.targetPlayerExpectedGeneralLocation)
            logbook.info('DONE building distmap after rebuilding intergen analysis')

        fromTile = bot.general
        if bot.locked_launch_point is None and bot._map.is_2v2 and bot.teammate_general is not None and bot.targetPlayerObj is not None:
            fromTile = BotTargeting.get_2v2_launch_point(bot)
            bot.locked_launch_point = fromTile

        if bot.locked_launch_point is not None:
            fromTile = bot.locked_launch_point
        else:
            startTime = time.perf_counter()
            targetPlayerObj = None
            if bot.targetPlayer != -1:
                targetPlayerObj = bot._map.players[bot.targetPlayer]
            if targetPlayerObj is None or not targetPlayerObj.knowsKingLocation:
                for genLaunchPoint in bot.launchPoints:
                    if genLaunchPoint is None:
                        logbook.info("wtf genlaunchpoint was none????")
                    elif enemyDistMap[genLaunchPoint] < enemyDistMap[fromTile]:
                        logbook.info(f"using launchPoint {genLaunchPoint}")
                        fromTile = genLaunchPoint

            bot.locked_launch_point = fromTile

        preferNeut = not isAllIn and not BotTargeting.is_ffa_situation(bot)
        preferEn = not isAllIn

        if BotStateQueries.is_still_ffa_and_non_dominant(bot):
            preferEn = False
            preferNeut = False

        with bot.perf_timer.begin_move_event(f'getting path to target {maxTile}'):
            path = BotPathingUtils.get_path_to_target(bot, maxTile, skipEnemyCities=isAllIn, preferNeutral=preferNeut, fromTile=fromTile, preferEnemy=preferEn)
            if path is None:
                path = BotPathingUtils.get_path_to_target(bot, maxTile, skipNeutralCities=False, skipEnemyCities=isAllIn, preferNeutral=preferNeut, fromTile=fromTile, preferEnemy=preferEn)

            bot.info(f'DEBUG: cutLen {cutLength} at {maxTile}: path {path}')
            if path is not None and cutLength is not None and path.length > cutLength:
                path = path.get_subsegment(cutLength, end=True)

        if bot.targetPlayer == -1 and bot._map.remainingPlayers > 2 and not bot._map.is_2v2:
            fakeGenPath = path.get_subsegment(11)
            logbook.info(f"FakeGenPath because FFA: {str(fakeGenPath)}")
            return fakeGenPath

        return path

    @staticmethod
    def get_max_explorable_undiscovered_tile(bot, minSpawnDist: int):
        # 4 and larger gets dicey
        depth = BotTargeting.get_safe_per_tile_bfs_depth(bot)

        if bot.undiscovered_priorities is None or bot._undisc_prio_turn != bot._map.turn:
            bot.undiscovered_priorities = BotTargeting.find_expected_1v1_general_location_on_undiscovered_map(
                bot,
                undiscoveredCounterDepth=depth,
                minSpawnDistance=minSpawnDist)
        bot._undisc_prio_turn = bot._map.turn

        maxAmount = 0
        maxTile = None
        for tile in bot._map.tiles_by_index:
            if bot.targetPlayer != -1 and not bot.armyTracker.valid_general_positions_by_player[bot.targetPlayer].raw[tile.tile_index]:
                continue
            if tile and maxAmount < bot.undiscovered_priorities.raw[tile.tile_index] and BotPathingUtils.distance_from_general(bot, tile) > minSpawnDist and (bot.teammate_general is None or BotPathingUtils.distance_from_teammate(bot, tile) > minSpawnDist):
                maxAmount = bot.undiscovered_priorities.raw[tile.tile_index]
                maxTile = tile
            if bot.targetPlayer == -1:
                if bot.info_render_general_undiscovered_prediction_values and bot.undiscovered_priorities.raw[tile.tile_index] > 0:
                    bot.viewInfo.bottomRightGridText[tile] = f'u{bot.undiscovered_priorities.raw[tile.tile_index]}'

        bot.viewInfo.add_targeted_tile(maxTile, TargetStyle.PURPLE)
        return maxTile

    @staticmethod
    def target_player_flank_path(bot):
        if bot.targetPlayer == -1:
            return None

        if bot.targetPlayer != -1:
            tp = bot.targetPlayerObj
            if tp.leftGame and bot._map.turn < tp.leftGameTurn + 50:
                remainingTurns = tp.leftGameTurn + 50 - bot._map.turn
                if tp.tileCount > 10 or tp.cityCount > 1 or (tp.general is not None and tp.general.army + remainingTurns // 2 < 42):
                    turns = max(8, remainingTurns - 15)
                    with bot.perf_timer.begin_move_event(f'Quick kill gather to player who left, {remainingTurns} until they arent capturable'):
                        move = BotGatherOps.timing_gather(
                            bot,
                            [bot.targetPlayerExpectedGeneralLocation],
                            force=True,
                            targetTurns=turns,
                            pruneToValuePerTurn=True)
                    if move is not None:
                        bot.info(f"quick-kill gather to opposing player who left! {move}")
                        return move

        return None

    @staticmethod
    def calculate_target_player(bot) -> int:
        targetPlayer = -1
        playerScore = 0

        if bot._map.remainingPlayers == 2:
            for player in bot._map.players:
                if player.index != bot.general.player and not player.dead and player.index not in bot._map.teammates:
                    return player.index

        allAfk = len(BotTargeting.get_afk_players(bot)) >= bot._map.remainingPlayers - 1 - len(bot._map.teammates)
        if allAfk or bot._map.is_2v2:
            playerScore = -10000000

        minStars = 10000
        starSum = 0
        for player in bot._map.players:
            minStars = min(minStars, player.stars)
            starSum += player.stars
        starAvg = starSum * 1.0 / len(bot._map.players)
        bot.playerTargetScores = [0 for i in range(len(bot._map.players))]
        generalPlayer = bot._map.players[bot.general.player]

        numVisibleEnemies = 0

        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates:
                continue
            seenPlayer = SearchUtils.count(player.tiles, lambda t: t.visible) > 0

        for player in bot._map.players:
            seenPlayer = SearchUtils.count(player.tiles, lambda t: t.visible) > 0
            if player.dead or player.index == bot._map.player_index or not seenPlayer or player.index in bot._map.teammates:
                continue

            curScore = 300

            if bot._map.remainingPlayers > 3:
                curScore = -1
                if player.aggression_factor < 10:
                    if numVisibleEnemies > 1:
                        curScore -= 50

            enGen = bot._map.generals[player.index]

            knowsWhereEnemyGeneralIsBonus = 100
            if bot._map.is_2v2:
                knowsWhereEnemyGeneralIsBonus = 1000
            if enGen is not None:
                curScore += knowsWhereEnemyGeneralIsBonus

            if player.leftGame and not player.dead:
                armyEnGenCutoffFactor = 0.75
                if enGen is not None:
                    if enGen.army < generalPlayer.standingArmy ** armyEnGenCutoffFactor:
                        bot.viewInfo.add_info_line(f'leftGame GEN bonus army generalPlayer.standingArmy ** {armyEnGenCutoffFactor} {generalPlayer.standingArmy ** armyEnGenCutoffFactor} > enGen.army {enGen.army}')
                        curScore += 300
                    else:
                        curScore += 2500 // player.tileCount
                factor = 0.95
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    bot.viewInfo.add_info_line(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 200
                factor = 0.88
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    bot.viewInfo.add_info_line(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 100
                factor = 0.81
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    bot.viewInfo.add_info_line(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 50
                factor = 0.75
                if generalPlayer.standingArmy > player.standingArmy ** factor:
                    bot.viewInfo.add_info_line(f'leftGame bonus army generalPlayer.standingArmy {generalPlayer.standingArmy} > player.standingArmy ** {factor} {player.standingArmy ** factor}')
                    curScore += 30

            alreadyTargetingBonus = 120
            if bot.targetPlayer != -1 and bot._map.players[bot.targetPlayer].aggression_factor < 40:
                alreadyTargetingBonus = 10

            curScore += player.aggression_factor
            if player.index == bot.targetPlayer:
                curScore += alreadyTargetingBonus

            curScore += player.aggression_factor

            if generalPlayer.standingArmy > player.standingArmy * 0.75:
                curScore += player.cityCount * 30
                curScore += player.tileCount
                curScore *= 1.2

            if player.knowsKingLocation or player.knowsAllyKingLocation:
                curScore += 100
                curScore *= 2

            if bot.generalApproximations[player.index][3] is not None:
                enApprox = bot.generalApproximations[player.index][3]
                genDist = BotPathingUtils.distance_from_general(bot, enApprox)
                if bot.teammate_general is not None:
                    genDist += bot._map.euclidDist(bot.teammate_general.x, bot.teammate_general.y, enApprox.x, enApprox.y)
                    genDist = genDist // 2
            else:
                logbook.info(f"           wot {bot._map.usernames[targetPlayer]} didn't have a gen approx tile???")
                genDist = bot._map.euclidDist(bot.generalApproximations[player.index][0], bot.generalApproximations[player.index][1], bot.general.x, bot.general.y)

                if bot.teammate_general is not None:
                    genDist += bot._map.euclidDist(bot.teammate_general.x, bot.teammate_general.y, bot.generalApproximations[player.index][0], bot.generalApproximations[player.index][1])
                    genDist = genDist // 2

            curScore = curScore + 2 * curScore / (max(10, genDist) - 2)

            if player.index != bot.targetPlayer and not bot._map.is_2v2:
                curScore = curScore * 0.9

            if player.standingArmy <= 0 or (player.tileCount < 4 and player.general is None) or (player.general is not None and player.general.army > player.standingArmy ** 0.95 and player.general.army > 75):
                curScore = -100

            if bot._map.remainingPlayers > 2 and not bot.opponent_tracker.winning_on_army(0.7, False, player.index) and not bot.opponent_tracker.winning_on_economy(0.7, 20, player.index):
                curScore = -200

            if 'PurdBlob' in bot._map.usernames[player.index]:
                curScore += 150

            if 'PurdPath' in bot._map.usernames[player.index]:
                curScore += 100

            if curScore > playerScore and player.index not in bot._map.teammates:
                playerScore = curScore
                targetPlayer = player.index
            bot.playerTargetScores[player.index] = curScore

        if bot._map.remainingPlayers > 2 and playerScore < -100 and not bot._map.is_2v2:
            return -1

        if targetPlayer == -1 and bot._map.is_2v2:
            for player in bot._map.players:
                if player.index != bot.general.player and player.index not in bot._map.teammates and not player.dead:
                    return player.index

        if targetPlayer != -1:
            logbook.info(f"target player: {bot._map.usernames[targetPlayer]} ({int(playerScore)})")

        return targetPlayer

    @staticmethod
    def find_hacky_path_to_find_target_player_spawn_approx(bot, minSpawnDist: int):
        if bot.targetPlayerObj is None or len(bot.targetPlayerObj.tiles) == 0:
            return None

        if not bot.undiscovered_priorities:
            depth = 7
            if len(bot._map.tiles_by_index) > 1000:
                depth = 6

            if len(bot._map.tiles_by_index) > 2500:
                depth = 5

            if len(bot._map.tiles_by_index) > 4000:
                depth = 4

            bot.undiscovered_priorities = BotTargeting.find_expected_1v1_general_location_on_undiscovered_map(
                bot,
                undiscoveredCounterDepth=depth,
                minSpawnDistance=minSpawnDist)

        def value_func(tile: Tile, prioObj):
            (realDist, negScore, dist, lastTile) = prioObj

            if realDist < minSpawnDist:
                return None

            score = 0 - negScore
            scoreOverDist = score / (realDist * dist + 1)
            return (scoreOverDist, 0 - realDist)

        def prio_func(tile: Tile, prioObj):
            (fakeDist, negScore, dist, lastTile) = prioObj
            if tile.player == bot.targetPlayer:
                negScore -= 200
            if tile.visible:
                fakeDist += 2
            else:
                negScore -= 100
            if lastTile is not None and not lastTile.visible and tile.visible:
                negScore += 10000
            undiscScore = bot.undiscovered_priorities.raw[tile.tile_index]
            negScore -= undiscScore
            realDist = BotPathingUtils.distance_from_general(bot, tile)
            return realDist, negScore, dist + 1, tile

        def skip_func(tile: Tile, prioObj):
            return tile.visible and tile.player != bot.targetPlayer

        startDict = {}
        for targetTile in bot.targetPlayerObj.tiles:
            startDict[targetTile] = ((BotPathingUtils.distance_from_general(bot, targetTile), 0, 0, None), 0)

        path = SearchUtils.breadth_first_dynamic_max(
            bot._map,
            startDict,
            valueFunc=value_func,
            maxTime=0.1,
            maxTurns=150,
            maxDepth=150,
            noNeutralCities=True,
            priorityFunc=prio_func,
            skipFunc=skip_func,
            noLog=True,
        )

        bot.viewInfo.add_info_line(f'hacky path {str(path)}...?')

        bot.viewInfo.color_path(PathColorer(path, 255, 0, 0))
        if path is not None:
            return path.tail.tile

        return None

    @staticmethod
    def find_expected_1v1_general_location_on_undiscovered_map(
            bot,
            undiscoveredCounterDepth: int,
            minSpawnDistance: int
    ) -> MapMatrixInterface[int]:
        localMaxTile = bot.general
        maxAmount: int = -1
        grid = MapMatrix(bot._map, 0)

        genDists = bot._map.get_distance_matrix_including_obstacles(bot.general)

        def tile_meets_criteria_for_value_around_general(t: Tile) -> bool:
            return (
                    not t.discovered
                    and t.isPathable
                    and (bot.targetPlayer == -1 or bot.armyTracker.valid_general_positions_by_player[bot.targetPlayer].raw[t.tile_index])
            )

        def tile_meets_criteria_for_general(t: Tile) -> bool:
            return tile_meets_criteria_for_value_around_general(t) and genDists.raw[t.tile_index] >= minSpawnDistance and (bot.teammate_general is None or BotPathingUtils.distance_from_teammate(bot, t) >= minSpawnDistance)

        for tile in bot._map.pathable_tiles:
            if tile_meets_criteria_for_general(tile):
                genDist = genDists.raw[tile.tile_index] / 2
                distFromCenter = BotPathingUtils.get_distance_from_board_center(bot, tile, center_ratio=0.25)

                initScore = genDist - distFromCenter
                counter = SearchUtils.Counter(0)
                if bot.info_render_general_undiscovered_prediction_values:
                    bot.viewInfo.bottomMidLeftGridText.raw[tile.tile_index] = f'u{initScore:.1f}'

                def count_undiscovered(curTile):
                    if tile_meets_criteria_for_value_around_general(curTile):
                        if curTile.isDesert:
                            counter.add(0.1)
                        elif curTile.isSwamp:
                            counter.add(0.05)
                        elif curTile.isCity:
                            counter.add(3)
                        else:
                            counter.add(1)

                SearchUtils.breadth_first_foreach(bot._map, [tile], undiscoveredCounterDepth, count_undiscovered, noLog=True)

                grid.raw[tile.tile_index] = counter.value + initScore
                if bot.info_render_general_undiscovered_prediction_values:
                    bot.viewInfo.bottomRightGridText.raw[tile.tile_index] = f'c{counter.value}'

                if counter.value > maxAmount:
                    localMaxTile = tile
                    maxAmount = counter.value

        if bot.targetPlayer == -1 or len(bot._map.players[bot.targetPlayer].tiles) == 0:
            def mark_undiscovered(curTile):
                if tile_meets_criteria_for_value_around_general(curTile):
                    bot._evaluatedUndiscoveredCache.append(curTile)
                    if bot.info_render_general_undiscovered_prediction_values:
                        bot.viewInfo.evaluatedGrid[curTile.x][curTile.y] = 1

            SearchUtils.breadth_first_foreach(bot._map, [localMaxTile], undiscoveredCounterDepth, mark_undiscovered, noLog=True)

        return grid

    @staticmethod
    def get_predicted_target_player_general_location(bot, skipDiscoveredAsNeutralFilter: bool = False) -> Tile:
        minSpawnDist = bot.armyTracker.min_spawn_distance

        if bot.targetPlayer == -1 and BotStateQueries.is_still_ffa_and_non_dominant(bot):
            bot.info(f'bypassed get_predicted_target_player_general_location because no target player and ffa')
            return bot.general

        if bot.targetPlayer == -1 or (len(bot._map.players) == 2 and len([t for t in filter(lambda tile: tile.visible, bot._map.players[bot.targetPlayer].tiles)])):
            with bot.perf_timer.begin_move_event('get_max_explorable_undiscovered_tile'):
                bot.info(f'DEBUG get_max_explorable_undiscovered_tile')
                return BotTargeting.get_max_explorable_undiscovered_tile(bot, minSpawnDist)

        if bot._map.generals[bot.targetPlayer] is not None:
            bot.info(f'DEBUG enemyGeneral')
            return bot._map.generals[bot.targetPlayer]

        maxTile = bot.general
        values = MapMatrix(bot._map, 0.0)

        if bot.armyTracker.connectedByPlayer[bot.targetPlayer] is not None:
            def foreachFunc(curTile: Tile, state: typing.Tuple[float, int]):
                (baseFloat, dist) = state
                values.raw[curTile.tile_index] += baseFloat / dist
                return (baseFloat, dist + 1)
            startTiles = {t: (bot.armyTracker.emergenceLocationMap[bot.targetPlayer][t] + 10.0, 1) for t in bot.armyTracker.connectedByPlayer[bot.targetPlayer] if bot.armyTracker.emergenceLocationMap[bot.targetPlayer][t] > 0}
            SearchUtils.breadth_first_foreach_with_state(bot._map, startTiles, 15, foreachFunc, None, noLog=True)

        maxAmount = 0

        for tile in bot._map.pathable_tiles:
            if tile.discovered or tile.isMountain or tile.isNotPathable or tile.isCity:
                continue

            foundValue = 0

            if not bot.armyTracker.valid_general_positions_by_player[bot.targetPlayer][tile]:
                continue

            if bot.armyTracker.emergenceLocationMap[bot.targetPlayer][tile] > 0:
                foundValue += bot.armyTracker.emergenceLocationMap[bot.targetPlayer][tile] * 10

            values.raw[tile.tile_index] = foundValue
            if foundValue > maxAmount:
                maxTile = tile
                maxAmount = foundValue
            if foundValue > 0 and bot.info_render_general_undiscovered_prediction_values:
                bot.viewInfo.midRightGridText[tile] = f'we{foundValue}'

        bot.viewInfo.add_targeted_tile(maxTile, TargetStyle.BLUE, radiusReduction=11)

        if maxTile is not None and maxTile != bot.general and not maxTile.isObstacle and not maxTile.isCity:
            bot.undiscovered_priorities = values
            logbook.info(
                f"Highest density undiscovered tile {str(maxTile)} with value {maxAmount} found")
            return maxTile

        if bot.targetPlayer != -1 and len(bot.targetPlayerObj.tiles) > 0:
            bot.viewInfo.add_info_line("target path failed, hacky gen approx attempt:")
            with bot.perf_timer.begin_move_event('find_hacky_path_to_find_target_player_spawn_approx'):
                maxTile = BotTargeting.find_hacky_path_to_find_target_player_spawn_approx(bot, minSpawnDist)
                if maxTile is not None and maxTile != bot.general and not maxTile.isObstacle and not maxTile.isCity:
                    bot.info(
                        f"Highest density undiscovered tile {str(maxTile)}")
                    return maxTile

            for tile in bot.targetPlayerObj.tiles:
                for adjTile in tile.movable:
                    if not adjTile.discovered and not adjTile.isObstacle and not adjTile.isCity:
                        bot.info(f"target path failed, falling back to {adjTile} - a random tile adj to en.")
                        return adjTile

        bot.viewInfo.add_info_line(f"target path failed, falling back to undiscovered path. minSpawnDist {minSpawnDist}")
        with bot.perf_timer.begin_move_event(f'fb{bot.targetPlayer} get_max_explorable_undiscovered_tile'):
            fallbackTile = BotTargeting.get_max_explorable_undiscovered_tile(bot, minSpawnDist)
            if fallbackTile is not None and fallbackTile != bot.general:
                bot.info(f"target path failed, falling back to {fallbackTile} - get_max_explorable_undiscovered_tile")
                return fallbackTile

        furthestDist = 0
        furthestTile = None
        for tile in bot._map.pathable_tiles:
            if tile.visible:
                continue
            if tile.isCity:
                continue

            d = BotPathingUtils.distance_from_general(bot, tile)
            if furthestDist < d < 999:
                furthestDist = d
                furthestTile = tile

        bot.info(f"target path fallback failed, {furthestTile} furthest {furthestDist} pathable reachable tile")

        if furthestTile is not None:
            return furthestTile

        gMov = next(iter(bot.general.movableNoObstacles))
        bot.info(f"target path fallback failed, returning {gMov} tile next to general.")
        return gMov

    @staticmethod
    def is_player_spawn_cramped(bot, spawnDist=-1) -> bool:
        if bot._spawn_cramped is not None:
            return bot._spawn_cramped

        if spawnDist == -1:
            bot.target_player_gather_targets = {t for t in bot.target_player_gather_path.tileList if not t.isSwamp and not (t.isDesert and t.isNeutral)}
            if len(bot.target_player_gather_targets) == 0:
                bot.target_player_gather_targets = bot.target_player_gather_path.tileSet
            spawnDist = bot.shortest_path_to_target_player.length

        tiles = [bot.general]

        counter = SearchUtils.Counter(0)

        spawnDist = spawnDist / 2.0

        def count_neutral(curTile: Tile):
            tileTerritory = bot.territories.territoryMap[curTile]
            isTileContested = bot._map.is_tile_enemy(curTile)
            isTileContested |= tileTerritory != bot.general.player and tileTerritory >= 0 and tileTerritory not in bot._map.teammates
            if not curTile.isNotPathable:
                counter.add(0.5)
            if not isTileContested:
                counter.add(0.5)

        counter.value = 0
        SearchUtils.breadth_first_foreach(bot._map, tiles, 8, count_neutral, noLog=True)
        count8 = counter.value

        counter.value = 0
        SearchUtils.breadth_first_foreach(bot._map, tiles, 6, count_neutral, noLog=True)
        count6 = counter.value

        counter.value = 0
        SearchUtils.breadth_first_foreach(bot._map, tiles, 4, count_neutral, noLog=True)
        count4 = counter.value

        enTerritoryStr = ''
        if bot.targetPlayer != -1:
            enemyTerritoryFoundCounter = SearchUtils.Counter(0)
            targetPlayer = bot._map.players[bot.targetPlayer]
            visibleTiles = [t for t in filter(lambda tile: tile.visible, targetPlayer.tiles)]
            enemyVisibleTileCount = len(visibleTiles)

            def count_enemy_territory(curTile: Tile, object):
                tileTerritory = bot.territories.territoryMap[curTile]
                isTileContested = bot._map.is_tile_enemy(curTile)
                isTileContested |= tileTerritory != bot.general.player and tileTerritory >= 0 and tileTerritory not in bot._map.teammates
                if isTileContested:
                    enemyTerritoryFoundCounter.add(1)

                if enemyTerritoryFoundCounter.value > enemyVisibleTileCount:
                    return True

                return False

            path = SearchUtils.breadth_first_dynamic(
                bot._map,
                tiles,
                count_enemy_territory,
                noNeutralCities=True,
                searchingPlayer=bot.general.player)

            if path is not None:
                territoryTile = path.tileList[-1]
                bot.viewInfo.add_targeted_tile(territoryTile, TargetStyle.RED)
                enTerritoryStr = f'enTerr d{path.length} @{str(territoryTile)}'
                spawnDist = path.length

        spawnDistFactor = spawnDist - 10

        thisPlayer = bot._map.players[bot.general.player]
        cap8 = 68 - 9 * (thisPlayer.cityCount - 1) + spawnDistFactor
        cap6 = 42 - 6 * (thisPlayer.cityCount - 1) + spawnDistFactor
        cap4 = 21 - 3 * (thisPlayer.cityCount - 1) + spawnDistFactor

        cramped = False
        if count8 < cap8 or count6 < cap6 or count4 < cap4:
            cramped = True

        bot.viewInfo.add_stats_line(f"Cramped: {cramped} 8[{count8}/{cap8}] 6[{count6}/{cap6}] 4[{count4}/{cap4}] spawnDistFactor[{spawnDistFactor}] {enTerritoryStr}")

        bot._spawn_cramped = cramped

        return cramped


BM.BotTargeting = BotTargeting
