import typing

import ExpandUtils
import logbook
from Algorithms import WatchmanRouteUtils
import SearchUtils
from BotModules.BotCombatQueries import BotCombatQueries
from BotModules.BotDefenseQueries import BotDefenseQueries
from BotModules.BotExpansionOps import BotExpansionOps
from BotModules.BotGatherOps import BotGatherOps
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotRendering import BotRendering
from BotModules.BotRepetition import BotRepetition
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotTargeting import BotTargeting
from BotModules.BotTimings import BotTimings
from Models import Move
from Path import Path
from Strategy.WinConditionAnalyzer import WinCondition
from ViewInfo import PathColorer
from base.client.tile import Tile
import BotModules as BM


class BotExplorationOps:
    @staticmethod
    def get_optimal_exploration(
            bot,
            turns,
            negativeTiles: typing.Set = None,
            valueFunc=None,
            priorityFunc=None,
            initFunc=None,
            skipFunc=None,
            minArmy=0,
            maxTime: float | None = None,
            emergenceRatio: float = 0.15,
            includeCities: bool | None = None,
    ) -> Path | None:
        if includeCities is None:
            includeCities = not bot.armyTracker.has_perfect_information_of_player_cities(bot.targetPlayer) and WinCondition.ContestEnemyCity in bot.win_condition_analyzer.viable_win_conditions

        toReveal = BotTargeting.get_target_player_possible_general_location_tiles_sorted(bot, elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=emergenceRatio, includeCities=includeCities)
        targetArmyLevel = BotDefenseQueries.determine_fog_defense_amount_available_for_tiles(bot, toReveal, bot.targetPlayer)

        for t in toReveal:
            BotRendering.mark_tile(bot, t, alpha=50)

        if len(toReveal) == 0:
            return None

        startArmies = sorted(BotCombatQueries.get_largest_tiles_as_armies(bot, bot.general.player, limit=3), key=lambda t: bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, t.tile))

        bestArmy = None
        bestThresh = None
        for startArmy in startArmies:
            if negativeTiles and startArmy.tile in negativeTiles:
                continue
            armyDiff = startArmy.value - targetArmyLevel
            dist = bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, startArmy.tile)
            if dist <= 0:
                dist = 1
            if armyDiff <= 0:
                thisThresh = -dist + armyDiff
            else:
                thisThresh = armyDiff / dist

            if bestArmy is None or bestThresh < thisThresh:
                bestThresh = thisThresh
                bestArmy = startArmy

        if bestArmy is None:
            return None

        startTile = bestArmy.tile

        with bot.perf_timer.begin_move_event(f'Watch {startTile} c{str(includeCities)[0]} tgA {targetArmyLevel}'):
            if maxTime is None:
                maxTime = BotTimings.get_remaining_move_time(bot) / 2

            path = WatchmanRouteUtils.get_watchman_path(
                bot._map,
                startTile,
                toReveal,
                timeLimit=maxTime,
            )

        if path is None or path.length == 0:
            return None

        revealedCount, maxKillTurns, minKillTurns, avgKillTurns, rawKillDistByTileMatrix, bestRevealedPath = WatchmanRouteUtils.get_revealed_count_and_max_kill_turns_and_positive_path(bot._map, path, toReveal, targetArmyLevel)
        if bestRevealedPath is not None:
            bot.info(f'WRPHunt (c{str(includeCities)[0]} ta{targetArmyLevel}) {startTile} {bestRevealedPath.length}t ({path.length}t) rev {revealedCount}/{len(toReveal)}, kill min{minKillTurns} max{maxKillTurns} avg{avgKillTurns:.1f}')
        else:
            bot.info(f'WRPHunt (c{str(includeCities)[0]} ta{targetArmyLevel}) {startTile} -NONE- ({path.length}t) rev {revealedCount}/{len(toReveal)}, kill min{minKillTurns} max{maxKillTurns} avg{avgKillTurns:.1f}')
            bestRevealedPath = None

        return bestRevealedPath

    @staticmethod
    def get_move_if_afk_player_situation(bot):
        afkPlayers = BotTargeting.get_afk_players(bot)
        allOtherPlayersAfk = len(afkPlayers) + 1 == bot._map.remainingPlayers
        numTilesVisible = 0
        if bot.targetPlayer != -1:
            numTilesVisible = len(bot._map.players[bot.targetPlayer].tiles)

        if allOtherPlayersAfk and numTilesVisible == 0:
            with bot.perf_timer.begin_move_event('AFK Player optimal EXPLORATION'):
                path = BotExplorationOps.get_optimal_exploration(bot, 30, None, minArmy=0, maxTime=0.04)
            if path is not None:
                bot.info(f'Rapid EXPLORE due to AFK player {bot.targetPlayer}:  {str(path)}')
                bot.finishing_exploration = True
                bot.viewInfo.add_info_line('Setting finishingExploration to True because allOtherPlayersAfk and found an explore path')
                return BotPathingUtils.get_first_path_move(bot, path)

            expansionNegatives = set()
            territoryMap = bot.territories.territoryMap
            with bot.perf_timer.begin_move_event('AFK Player optimal EXPANSION'):
                if bot.teammate_general is not None:
                    expansionNegatives.add(bot.teammate_general)
                expUtilPlan = ExpandUtils.get_round_plan_with_expansion(
                    bot._map,
                    bot.general.player,
                    bot.targetPlayer,
                    15,
                    bot.board_analysis,
                    territoryMap,
                    bot.tileIslandBuilder,
                    expansionNegatives,
                    bot.captureLeafMoves,
                    includeExpansionSearch=True,
                    allowLeafMoves=False,
                    viewInfo=bot.viewInfo,
                    time_limit=0.03)

                path = expUtilPlan.selected_option

            if path is not None:
                bot.finishing_exploration = True
                bot.info(f'Rapid EXPAND due to AFK player {bot.targetPlayer}:  {str(path)}')
                return BotPathingUtils.get_first_path_move(bot, path)

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
                        bot.info(f'quick-kill gather to opposing player who left! {move}')
                        return move

            if allOtherPlayersAfk and bot.targetPlayerExpectedGeneralLocation is not None and bot.targetPlayerExpectedGeneralLocation.isGeneral:
                with bot.perf_timer.begin_move_event(f'quick-kill gather to opposing player!'):
                    move = BotGatherOps.timing_gather(
                        bot,
                        [bot.targetPlayerExpectedGeneralLocation],
                        force=True,
                        pruneToValuePerTurn=True)
                if move is not None:
                    bot.info(f'quick-kill gather to opposing player! {move}')
                    return move

        return None

    @staticmethod
    def find_flank_defense_move(bot, defenseCriticalTileSet: typing.Set[Tile], highPriority: bool = False) -> Move | None:
        # this is not called often enough for this to matter and the circular reference here is hell
        from BotModules.BotDefense import BotDefense
        pathToCheck = bot.sketchiest_potential_inbound_flank_path

        if bot.enemy_attack_path is not None and bot.likely_kill_push:
            bot.info(f'~~risk threat - replacing flank with risk threat BC likely_kill_push')
            pathToCheck = bot.enemy_attack_path
        elif BotTargeting.is_ffa_situation(bot):
            return None

        checkFlank = pathToCheck is not None and (
                pathToCheck.tail.tile in bot.board_analysis.flank_danger_play_area_matrix
                or pathToCheck.tail.tile in bot.board_analysis.core_play_area_matrix
        )

        if pathToCheck:
            pathToCheck = pathToCheck.get_subsegment_excluding_trailing_visible()

        coreNegs = defenseCriticalTileSet.copy()
        coreNegs.update(bot.win_condition_analyzer.defend_cities)
        coreNegs.update(bot.win_condition_analyzer.contestable_cities)

        if highPriority and pathToCheck:
            winningMassivelyOnArmy = bot.opponent_tracker.winning_on_army(byRatio=1.4) and bot.opponent_tracker.winning_on_economy(byRatio=1.15)
            winningMassivelyOnEcon = bot.opponent_tracker.winning_on_army(byRatio=1.1) and bot.opponent_tracker.winning_on_economy(byRatio=1.4)
            winningInTheMiddle = bot.opponent_tracker.winning_on_army(byRatio=1.25) and bot.opponent_tracker.winning_on_economy(byRatio=1.05, offset=-25)
            winningByEnoughToBeSuperCareful = winningMassivelyOnArmy or winningMassivelyOnEcon or winningInTheMiddle

            flankIsCloserThanThreeFifths = bot.distance_from_general(pathToCheck.tail.tile) < 3 * bot.shortest_path_to_target_player.length // 5
            if winningByEnoughToBeSuperCareful and flankIsCloserThanThreeFifths:
                turns = 3 + (bot.timings.get_turns_left_in_cycle(bot._map.turn) + 1) % 4
                with bot.perf_timer.begin_move_event(f'superCareful flank gath {turns}t'):
                    startTiles = pathToCheck.convert_to_dist_dict(offset=0 - pathToCheck.length)
                    for t in list(startTiles.keys()):
                        if t.isSwamp or SearchUtils.any_where(t.movable, lambda m: m.isSwamp):
                            startTiles.pop(t)
                    move = None
                    if len(startTiles) > 0:
                        move, valGathered, turnsUsed, nodes = BotGatherOps.get_gather_to_target_tiles(
                            bot,
                            startTiles,
                            maxTime=0.002,
                            gatherTurns=turns,
                            negativeSet=defenseCriticalTileSet,
                            targetArmy=1,
                            useTrueValueGathered=True,
                            includeGatherTreeNodesThatGatherNegative=False,
                            maximizeArmyGatheredPerTurn=True,
                            priorityMatrix=BotExpansionOps.get_expansion_weight_matrix(bot, mult=10))

                    if move:
                        forcedHalf = False
                        if 4 < valGathered <= move.source.army // 2 and not BotPathingUtils.is_move_towards_enemy(bot, move):
                            move.move_half = True
                            forcedHalf = True
                        bot.info(f'superCareful flank gath for {turns}t: {move} ({valGathered} in {turnsUsed}t). Half {forcedHalf}')
                        return move

                leafMove = BotExplorationOps._get_vision_expanding_available_move(bot, coreNegs, pathToCheck)
                if leafMove is not None:
                    return leafMove

            return None

        if BotStateQueries.is_still_ffa_and_non_dominant(bot):
            return None

        leafMove = BotExplorationOps._get_vision_expanding_available_move(bot, coreNegs, pathToCheck)
        if leafMove is not None:
            return leafMove

        if not checkFlank:
            return None

        if checkFlank:
            leafMove = BotDefense._get_flank_defense_leafmove(bot, pathToCheck, coreNegs)
            if leafMove is not None:
                bot.info(f'LEAF proactive flank vision defense {str(leafMove)}')
                return leafMove

        negs = coreNegs.copy()
        negs.update([
            firstMove.source
            for p in bot.expansion_plan.all_paths
            for firstMove in [p.get_first_move()]
            if firstMove is not None and firstMove.source.delta.armyDelta == 0
        ])
        flankDefMove = BotDefense._get_flank_vision_defense_move_internal(bot,
            pathToCheck,
            negs,
            atDist=bot.board_analysis.within_flank_danger_play_area_threshold)
        if flankDefMove is not None:
            bot.info(f'proactive flank vision defense {str(flankDefMove)}')
            return flankDefMove

        flankDefMove = BotDefense._get_flank_vision_defense_move_internal(bot,
            pathToCheck,
            coreNegs,
            atDist=bot.board_analysis.within_flank_danger_play_area_threshold)
        if flankDefMove is not None:
            bot.info(f'No exp negs proactive flank vision defense {str(flankDefMove)}')
            return flankDefMove

        return None

    @staticmethod
    def explore_target_player_undiscovered(bot, negativeTiles: typing.Set[Tile] | None, onlyHuntGeneral: bool | None = None, maxTime: float | None = None) -> Path | None:
        if negativeTiles:
            negativeTiles = negativeTiles.copy()
        if bot._map.turn < 50 or bot.targetPlayer == -1:
            return None

        turnInCycle = bot.timings.get_turn_in_cycle(bot._map.turn)
        exploringUnknown = bot._map.generals[bot.targetPlayer] is None

        genPlayer = bot._map.players[bot.general.player]
        behindOnCities = genPlayer.cityCount < bot._map.players[bot.targetPlayer].cityCount

        if not BotStateQueries.is_all_in(bot, ):
            if bot.explored_this_turn:
                logbook.info("(skipping new exploration because already explored this turn)")
                return None
            if not bot.finishing_exploration and behindOnCities:
                logbook.info("(skipping new exploration because behind on cities and wasn't finishing exploration)")
                return None

        enGenPositions = bot.armyTracker.valid_general_positions_by_player[bot.targetPlayer]

        for player in bot._map.players:
            if not player.dead and player.team == bot.targetPlayerObj.team and player.index != bot.targetPlayer:
                enGenPositions = enGenPositions.copy()
                for i, val in enumerate(bot.armyTracker.valid_general_positions_by_player[player.index].raw):
                    enGenPositions.raw[i] = enGenPositions.raw[i] or val

        if onlyHuntGeneral is None:
            onlyHuntGeneral = bot.armyTracker.has_perfect_information_of_player_cities(bot.targetPlayer)

        if onlyHuntGeneral:
            for tile in bot._map.get_all_tiles():
                if not bot._map.is_tile_friendly(tile) and not enGenPositions[tile]:
                    negativeTiles.add(tile)

        bot.explored_this_turn = True
        turns = bot.timings.cycleTurns - turnInCycle - 7
        minArmy = max(12, int(genPlayer.standingArmy ** 0.75) - 10)
        bot.info(f"Forcing explore to t{turns} and minArmy to {minArmy}")
        if BotStateQueries.is_all_in(bot, ) and not bot.is_all_in_army_advantage and not bot.all_in_city_behind:
            turns = 15
            minArmy = int(genPlayer.standingArmy ** 0.83) - 10
            bot.info(f"Forcing explore to t{turns} and minArmy to {minArmy} because BotStateQueries.is_all_in(self, )")
        elif turns < 6:
            logbook.info(f"Forcing explore turns to minimum of 5, was {turns}")
            turns = 5
        elif turnInCycle < 6 and exploringUnknown:
            logbook.info(f"Forcing explore turns to minimum of 6, was {turns}")
            turns = 6

        if bot._map.turn < 100:
            return None

        path = BotExplorationOps.get_optimal_exploration(bot, turns, negativeTiles, minArmy=minArmy, maxTime=maxTime)
        if path:
            logbook.info(f"Oh no way, explore found a path lol? {str(path)}")
            tilesRevealed = set()
            score = 0
            node = path.start
            while node is not None:
                if not node.tile.discovered and bot.armyTracker.emergenceLocationMap[bot.targetPlayer][node.tile] > 0 and (not onlyHuntGeneral or enGenPositions.raw[node.tile.tile_index]):
                    score += bot.armyTracker.emergenceLocationMap[bot.targetPlayer][node.tile] ** 0.5
                for adj in node.tile.adjacents:
                    if not adj.discovered and (not onlyHuntGeneral or enGenPositions[adj]):
                        tilesRevealed.add(adj)
                node = node.next
            revealedPerMove = len(tilesRevealed) / path.length
            scorePerMove = score / path.length
            bot.viewInfo.add_info_line(
                f"hunting tilesRevealed {len(tilesRevealed)} ({revealedPerMove:.2f}), Score {score} ({scorePerMove:.2f}), path.length {path.length}")
            if ((revealedPerMove > 0.5 and scorePerMove > 4)
                    or (revealedPerMove > 0.8 and scorePerMove > 1)
                    or revealedPerMove > 1.5):
                bot.finishing_exploration = True
                bot.info(
                    f"NEW hunting, search turns {turns}, minArmy {minArmy}, allIn {bot.is_all_in_losing} finishingExp {bot.finishing_exploration} ")
                return path
            else:
                logbook.info("path wasn't good enough, discarding")

        return None

    @staticmethod
    def try_find_exploration_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        genPlayer = bot._map.players[bot.general.player]

        largeTileThresh = 15 * genPlayer.standingArmy / genPlayer.tileCount
        haveLargeTilesStill = len(SearchUtils.where(genPlayer.tiles, lambda tile: tile.army > largeTileThresh)) > 0
        logbook.info(
            "Will stop finishingExploration if we don't have tiles larger than {:.1f}. Have larger tiles? {}".format(
                largeTileThresh, haveLargeTilesStill))

        demolishingTargetPlayer = (bot.opponent_tracker.winning_on_army(1.5, useFullArmy=False, againstPlayer=bot.targetPlayer)
                                   and bot.opponent_tracker.winning_on_economy(1.5, cityValue=10, againstPlayer=bot.targetPlayer))

        allInAndKnowsGenPosition = (
                (bot.is_all_in_army_advantage or bot.all_in_losing_counter > bot.targetPlayerObj.tileCount // 3)
                and bot.targetPlayerExpectedGeneralLocation.isGeneral
                and not bot.all_in_city_behind
        )
        targetPlayer = bot._map.players[bot.targetPlayer]
        stillDontKnowAboutEnemyCityPosition = len(targetPlayer.cities) + 1 < targetPlayer.cityCount
        stillHaveSomethingToSearchFor = (
                (BotStateQueries.is_all_in(bot, ) or bot.finishing_exploration or demolishingTargetPlayer)
                and (not bot.targetPlayerExpectedGeneralLocation.isGeneral or stillDontKnowAboutEnemyCityPosition)
        )

        logbook.info(
            f"stillDontKnowAboutEnemyCityPosition: {stillDontKnowAboutEnemyCityPosition}, allInAndKnowsGenPosition: {allInAndKnowsGenPosition}, stillHaveSomethingToSearchFor: {stillHaveSomethingToSearchFor}")
        if not allInAndKnowsGenPosition and stillHaveSomethingToSearchFor and not bot.defend_economy:
            undiscNeg = defenseCriticalTileSet.copy()

            if (
                    bot.all_in_city_behind
                    or (
                    bot.is_all_in_army_advantage
                    and bot.opponent_tracker.winning_on_economy(byRatio=0.8, cityValue=50)
            )
            ):
                path = BM.BotCityOps.BotCityOps.get_quick_kill_on_enemy_cities(bot, defenseCriticalTileSet)
                if path is not None:
                    bot.info(f'ALL IN ARMY ADVANTAGE CITY CONTEST {str(path)}')
                    return BotPathingUtils.get_first_path_move(bot, path)

                for contestedCity in bot.cityAnalyzer.owned_contested_cities:
                    undiscNeg.add(contestedCity)

            timeCap = 0.03
            if allInAndKnowsGenPosition:
                timeCap = 0.06

            bot.viewInfo.add_info_line(
                f"exp: unknownEnCity: {stillDontKnowAboutEnemyCityPosition}, allInAgainstGen: {allInAndKnowsGenPosition}, stillSearch: {stillHaveSomethingToSearchFor}")
            with bot.perf_timer.begin_move_event('Attempt to fin/cont exploration'):
                for city in bot._map.players[bot.general.player].cities:
                    undiscNeg.add(city)

                if bot.target_player_gather_path is not None:
                    halfTargetPath = bot.target_player_gather_path.get_subsegment(
                        bot.target_player_gather_path.length // 2)
                    undiscNeg.add(bot.general)
                    for tile in halfTargetPath.tileList:
                        undiscNeg.add(tile)
                path = BotExplorationOps.explore_target_player_undiscovered(bot, undiscNeg, maxTime=timeCap)
                if path is not None:
                    bot.viewInfo.color_path(PathColorer(path, 120, 150, 127, 200, 12, 100))
                    if not BotPathingUtils.is_path_moving_mostly_away(bot, path, bot.board_analysis.intergeneral_analysis.bMap):
                        valueSubsegment = BotPathingUtils.get_value_per_turn_subsegment(bot, path, minLengthFactor=0)
                        if valueSubsegment.length != path.length:
                            logbook.info(f"BAD explore_target_player_undiscovered")
                            bot.info(
                                f"WHOAH, tried to make a bad exploration path...? Fixed with {str(valueSubsegment)}")
                            path = valueSubsegment
                        move = BotPathingUtils.get_first_path_move(bot, path)
                        if not BotRepetition.detect_repetition(bot, move, 7, 2):
                            if bot.is_all_in_army_advantage:
                                bot.all_in_army_advantage_counter -= 2
                            return move
                        else:
                            bot.info('bypassed hunting due to repetitions.')
                    else:
                        bot.info(f'IGNORING BAD HUNTING PATH BECAUSE MOVES AWAY FROM GEN APPROX')

        return None

    @staticmethod
    def try_get_enemy_territory_exploration_continuation_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if bot.targetPlayer == -1:
            return None

        if BotStateQueries.is_all_in(bot, ):
            path = BotExplorationOps.explore_target_player_undiscovered(bot, defenseCriticalTileSet, onlyHuntGeneral=True)
            if path is not None:
                bot.info(f'all-in exploration move...? {str(path)}')
                return BotPathingUtils.get_first_path_move(bot, path)
            return None

        if bot.timings.get_turns_left_in_cycle(bot._map.turn) < 42:
            return None

        if bot.armyTracker.has_perfect_information_of_player_cities_and_general(bot.targetPlayer):
            return None

        armyCutoff = 4 + 4 * int(bot.player.standingArmy / bot.player.tileCount)
        if bot.defend_economy:
            armyCutoff *= 2
            armyCutoff += 10

        logbook.info(f'EN TERRITORY CONT EXP, armyCutoff {armyCutoff}')
        move = BotExpansionOps._get_expansion_plan_exploration_move(bot, armyCutoff, defenseCriticalTileSet)

        if move is not None:
            BotExpansionOps.try_find_expansion_move(bot, defenseCriticalTileSet, timeLimit=BotTimings.get_remaining_move_time(bot))
            move = BotExpansionOps._get_expansion_plan_exploration_move(bot, armyCutoff, defenseCriticalTileSet)
            if move is not None:
                bot.info(f'EN TERRITORY CONT EXP! {move} - armyCutoff {armyCutoff}')
                return move

        return None

    @staticmethod
    def _get_vision_expanding_available_move(bot, coreNegs: typing.Set[Tile], pathToCheckForVisionOf: Path | None = None) -> Move | None:
        bestWeighted = 3
        bestMove = None

        if pathToCheckForVisionOf is None:
            pathToCheckForVisionOf = bot.sketchiest_potential_inbound_flank_path
        if pathToCheckForVisionOf is None:
            return None

        hidden = {t for t in pathToCheckForVisionOf.tileList if not t.visible}

        alreadyInExpPlan = not hidden.isdisjoint(bot.expansion_plan.plan_tiles)

        if bot.timings.get_turn_in_cycle(bot._map.turn) >= 6 and not alreadyInExpPlan:
            return None

        if alreadyInExpPlan:
            lastNonVisibleTile = None
            lenWithFog = 0
            for dist, t in enumerate(pathToCheckForVisionOf.tileList):
                if not t.visible:
                    lastNonVisibleTile = t
                    lenWithFog = dist

            fullDist = lenWithFog + bot.board_analysis.intergeneral_analysis.aMap[lastNonVisibleTile]
            midDist = fullDist // 2
            closestToMid = None
            closestToMidDist = 100000
            cutoff = BotTargeting.get_median_tile_value(bot, 85) + 2
            for p in bot.expansion_plan.all_paths:
                if not isinstance(p, Path):
                    continue
                if (p.value > 10 or p.length > 10 or (p.length > 5 and p.econValue / p.length < 1.5)) and not bot.is_all_in_army_advantage and not bot.is_winning_gather_cyclic and not bot.defend_economy:
                    continue

                if bot.likely_kill_push and p.length > 2:
                    continue

                if p.start.tile in bot.target_player_gather_path.tileSet or p.start.tile.isCity or p.start.tile.isGeneral:
                    continue

                intersection = hidden.intersection(p.tileList)
                if len(intersection) > 0:
                    for t in intersection:
                        tDist = abs(bot.board_analysis.intergeneral_analysis.aMap[t] - bot.board_analysis.intergeneral_analysis.bMap[t])
                        if tDist < closestToMidDist:
                            closestToMid = p
                            closestToMidDist = tDist

            if closestToMid is not None:
                move = closestToMid.get_first_move()
                bot.info(f'EXP plan included vision expansion {move}')
                bot.curPath = closestToMid
                return move

        if bot.timings.get_turn_in_cycle(bot._map.turn) >= 6:
            return None

        for leafMove in bot.captureLeafMoves:
            if leafMove.dest.isSwamp:
                continue
            dist = bot._map.get_distance_between(bot.general, leafMove.dest)

            if leafMove.source in coreNegs:
                continue

            revealed = 0
            anyFog = False
            for t in leafMove.dest.adjacents:
                if not t.discovered and t.player != -1:
                    revealed += 2
                if t in bot.board_analysis.flankable_fog_area_matrix:
                    anyFog = True

            if not anyFog or revealed == 0:
                continue

            weighted = dist + revealed
            if dist < 2 or weighted < bestWeighted:
                continue
            bestMove = leafMove
            bestWeighted = weighted

        if bestMove is not None:
            bot.info(f'vision expansion leaf {str(bestMove)}')

        return bestMove