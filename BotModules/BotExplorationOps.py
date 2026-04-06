import typing

import ExpandUtils
import logbook
from Algorithms import WatchmanRouteUtils
import SearchUtils
from BotModules.BotCombatQueries import BotCombatQueries
from BotModules.BotDefenseQueries import BotDefenseQueries
from BotModules.BotGatherOps import BotGatherOps
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotRendering import BotRendering
from BotModules.BotTargeting import BotTargeting
from BotModules.BotTimings import BotTimings
from Path import Path
from Strategy.WinConditionAnalyzer import WinCondition


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
