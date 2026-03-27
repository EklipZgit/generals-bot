from StrategyModels import CycleStatsData
from Directives import Timings
from DebugHelper import DebugHelper
from Path import Path
import SearchUtils
import logbook
import random


class BotTimings:
    @staticmethod
    def is_player_aggressive(bot, player: int, turnPeriod: int = 50) -> bool:
        if player in bot._map.teammates:
            return False

        pObj = bot._map.players[player]
        if pObj.dead:
            return False
        if pObj.leftGame:
            return False

        if pObj.aggression_factor > 120:
            return True

        return False

    @staticmethod
    def set_all_in_cycle_to_hit_with_current_timings(bot, cycle: int, bufferTurnsEndOfCycle: int = 5):
        turnsLeftInCurrentCycle = bot.timings.cycleTurns - bot.timings.get_turn_in_cycle(bot._map.turn)
        bot.all_in_army_advantage_counter = cycle - turnsLeftInCurrentCycle + bufferTurnsEndOfCycle
        bot.all_in_army_advantage_cycle = cycle

    @staticmethod
    def get_opponent_cycle_stats(bot) -> CycleStatsData | None:
        if bot.targetPlayer == -1:
            return None

        return bot.opponent_tracker.get_current_cycle_stats_by_player(bot.targetPlayer)

    @staticmethod
    def _get_approximate_greedy_turns_available(bot) -> int:
        if bot.targetPlayer == -1 or bot.target_player_gather_path is None:
            return 5

        if bot.is_player_spawn_cramped(spawnDist=bot.shortest_path_to_target_player.length):
            return 0

        defensiveTiles = list(bot.target_player_gather_path.tileList)
        defensiveTiles.extend([c for c in bot.player.cities if bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix[c] is not None and bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix[
            c].distance < bot.board_analysis.intergeneral_analysis.shortestPathWay.distance + 3])

        frArmy = bot.sum_friendly_army_near_or_on_tiles(defensiveTiles, distance=0, player=bot.general.player)
        enArmyOffset = 0
        if bot.enemy_attack_path:
            enArmyOffset = bot.sum_friendly_army_near_or_on_tiles([t for t in bot.enemy_attack_path.tileList if t.visible], distance=0, player=bot.targetPlayer)

        approxGreedyTurnsAvail = bot.opponent_tracker.get_approximate_greedy_turns_available(
            bot.targetPlayer,
            ourArmyNonIncrement=frArmy + bot.shortest_path_to_target_player.length // 2,
            cityLimit=None,
            opponentArmyOffset=enArmyOffset
        )

        finalGreedTurnsAvail = approxGreedyTurnsAvail
        prevGreed = bot.approximate_greedy_turns_avail
        if approxGreedyTurnsAvail == prevGreed:
            bot.viewInfo.add_info_line(f'greed stayed same, decrementing by 1 from {approxGreedyTurnsAvail} to {finalGreedTurnsAvail}')
            finalGreedTurnsAvail -= 1
        elif approxGreedyTurnsAvail < prevGreed - 1:
            bot.viewInfo.add_info_line(f'GREED TURNS DROPPED FROM {prevGreed} TO {approxGreedyTurnsAvail}')
        elif approxGreedyTurnsAvail > prevGreed:
            if approxGreedyTurnsAvail > prevGreed + 1:
                bot.viewInfo.add_info_line(f'greed increase from {prevGreed} to {approxGreedyTurnsAvail}')
            else:
                bot.viewInfo.add_info_line(f'greed increase BY 1 from {prevGreed} to {approxGreedyTurnsAvail}')

        bot.viewInfo.add_stats_line(f'Approx greedT: {finalGreedTurnsAvail} (our def {frArmy} opp enArmyOffset {enArmyOffset} -> {approxGreedyTurnsAvail})')

        return finalGreedTurnsAvail

    @staticmethod
    def prune_timing_split_if_necessary(bot):
        if bot.target_player_gather_path is None:
            return

        if bot.is_ffa_situation() and bot._map.turn < 150:
            return

        splitTurn = bot.timings.get_turn_in_cycle(bot._map.turn)
        tilesUngathered = SearchUtils.count(
            bot._map.pathable_tiles,
            lambda tile: (
                    tile.player == bot.general.player
                    and tile not in bot.target_player_gather_path.tileSet
                    and tile.army > 1
            )
        )

        player = bot._map.players[bot.general.player]
        if tilesUngathered - player.cityCount - 1 < 1:
            timingAdjusted = splitTurn + tilesUngathered
            if timingAdjusted < bot.timings.launchTiming:
                bot.viewInfo.add_info_line(f"Moving up launch timing from {bot.timings.launchTiming} to splitTurn {splitTurn} + tilesUngathered {tilesUngathered} = ({timingAdjusted})")
                bot.timings.launchTiming = timingAdjusted
                bot.timings.splitTurns = timingAdjusted

    @staticmethod
    def get_remaining_move_time(bot) -> float:
        used = bot.perf_timer.get_elapsed_since_update(bot._map.turn)
        moveCycleTime = 0.5
        latencyBuffer = 0.26
        allowedLatest = moveCycleTime - latencyBuffer
        remaining = allowedLatest - used
        if DebugHelper.IS_DEBUGGING:
            return max(remaining, 0.1)
        return remaining

    @staticmethod
    def timing_cycle_ended(bot):
        bot.is_winning_gather_cyclic = False
        bot.viewInfo.add_info_line(f'Timing cycle ended, turn {bot._map.turn}')
        bot.cities_gathered_this_cycle = set()
        bot.tiles_gathered_to_this_cycle = set()
        bot.tiles_captured_this_cycle = set()
        bot.tiles_evacuated_this_cycle = set()
        bot.city_expand_plan = None
        bot.curPath = None
        player = bot._map.players[bot.general.player]
        cityCount = player.cityCount

        citiesAvoided = 0
        if player.cityCount > 4:
            for city in sorted(player.cities, key=lambda c: c.army):
                if citiesAvoided >= cityCount // 2 - 2:
                    break
                citiesAvoided += 1
                bot.viewInfo.add_info_line(f'AVOIDING CITY {repr(city)}')
                bot.cities_gathered_this_cycle.add(city)

        bot.locked_launch_point = None
        bot.flanking = False

    @staticmethod
    def get_timings_old(bot) -> Timings:
        with bot.perf_timer.begin_move_event('GatherAnalyzer scan'):
            bot.gatherAnalyzer.scan()

        countOnPath = 0
        if bot.target_player_gather_targets is not None:
            countOnPath = SearchUtils.count(bot.target_player_gather_targets, lambda tile: bot._map.is_tile_friendly(tile))
        randomVal = random.randint(-1, 2)
        cycleDuration = 50
        gatherSplit = 0
        realDist = bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation)
        longSpawns = bot.target_player_gather_path is not None and realDist > 22
        genPlayer = bot._map.players[bot.general.player]
        targPlayer = None
        if bot.targetPlayer != -1:
            targPlayer = bot._map.players[bot.targetPlayer]
            bot.opponent_tracker.get_tile_differential()

        frTileCount = genPlayer.tileCount
        for teammate in bot._map.teammates:
            teamPlayer = bot._map.players[teammate]
            frTileCount += teamPlayer.tileCount

        if False and longSpawns and genPlayer.tileCount > 80:
            if bot.is_all_in():
                if genPlayer.tileCount > 80:
                    cycleDuration = 100
                    gatherSplit = 70
                else:
                    gatherSplit = min(40, genPlayer.tileCount - 10)
            elif genPlayer.tileCount > 120:
                cycleDuration = 100
                gatherSplit = 60
            elif genPlayer.tileCount > 100:
                cycleDuration = 100
                gatherSplit = 55
        else:
            if bot.is_all_in():
                if genPlayer.tileCount > 95:
                    cycleDuration = 100
                    gatherSplit = 76
                else:
                    cycleDuration = 50
                    gatherSplit = 35
            elif genPlayer.tileCount - countOnPath > 140 or realDist > 35:
                cycleDuration = 100
                gatherSplit = 65
            elif genPlayer.tileCount - countOnPath > 120 or realDist > 29:
                gatherSplit = 26
            elif genPlayer.tileCount - countOnPath > 100:
                gatherSplit = 26
            elif genPlayer.tileCount - countOnPath > 85:
                gatherSplit = 26
            elif genPlayer.tileCount - countOnPath > 65:
                gatherSplit = 25
            elif genPlayer.tileCount - countOnPath > 45:
                gatherSplit = 24
            elif genPlayer.tileCount - countOnPath > 30:
                gatherSplit = 23
            elif genPlayer.tileCount - countOnPath > 21:
                gatherSplit = 21
            else:
                gatherSplit = genPlayer.tileCount - countOnPath
                randomVal = 0

            gatherSplit = min(gatherSplit, genPlayer.tileCount - countOnPath)

        if bot._map.turn < 100:
            cycleDuration = 50
            gatherSplit = 20

        gatherSplit = min(gatherSplit, genPlayer.tileCount - countOnPath)

        if bot.targetPlayer == -1 and bot._map.remainingPlayers == 2:
            gatherSplit += 3
        gatherSplit += randomVal

        quickExpandSplit = 0
        if bot._map.turn > 50:
            if bot.targetPlayer != -1:
                maxAllowed = bot.behavior_max_allowed_quick_expand
                winningBasedMin = int(targPlayer.tileCount - genPlayer.tileCount + genPlayer.tileCount / 8)
                quickExpandSplit = min(maxAllowed, max(0, winningBasedMin))
                logbook.info(f"quickExpandSplit: {quickExpandSplit}")

        if bot.defend_economy:
            gatherSplit += 3
            quickExpandSplit = 0

        if bot.currently_forcing_out_of_play_gathers:
            gatherSplit += 3
            quickExpandSplit = 0

        if bot.is_still_ffa_and_non_dominant():
            quickExpandSplit = 0
            gatherSplit += 4
            if bot.targetPlayer != -1 and bot.targetPlayerObj.aggression_factor > 150:
                gatherSplit = 50 - bot.shortest_path_to_target_player.length - 4

        disallowEnemyGather = False

        offset = bot._map.turn % cycleDuration
        if offset % 50 != 0:
            bot.viewInfo.add_info_line(f"offset being reset to 0 from {offset}")
            offset = 0

        pathValueWeight = 0
        pathLength = 8
        if bot.target_player_gather_path is not None:
            subsegment = bot.target_player_gather_path.get_subsegment(int(bot.target_player_gather_path.length // 2))
            subsegment.calculate_value(bot.general.player, teams=bot._map.team_ids_by_player_index)
            pathValueWeight = max(pathValueWeight, int(max(1.0, subsegment.value) ** 0.75))
            pathLength = max(pathLength, bot.target_player_gather_path.length)

        launchTiming = cycleDuration - pathValueWeight - pathLength - 4 + bot.behavior_launch_timing_offset

        tileDiff = bot.opponent_tracker.get_tile_differential()
        if tileDiff < 2:
            back = max(-10, tileDiff // 2) - 2
            bot.viewInfo.add_info_line(f'gathSplit back {back} turns due to tileDiff {tileDiff}')
            gatherSplit += back

        if bot.flanking:
            gatherSplit += bot.behavior_flank_launch_timing_offset
            launchTiming = gatherSplit
            quickExpandSplit = 0

        if bot.teammate_path is not None and bot.target_player_gather_path is not None and bot.target_player_gather_path.start.tile == bot.teammate_general:
            gatherSplit -= bot.teammate_path.length // 2 + 2
            launchTiming = gatherSplit

        isOurPathAMostlyFogAltPath = False
        if bot.target_player_gather_path is not None:
            numFog = bot.get_undiscovered_count_on_path(bot.target_player_gather_path)
            numEn = bot.get_enemy_count_on_path(bot.target_player_gather_path)

            overage = 2 * numFog - 1 * bot.target_player_gather_path.length // 2 - numEn
            if overage > 0 and bot._map.turn > 85 and numEn < bot.target_player_gather_path.length // 3:
                isOurPathAMostlyFogAltPath = True
                bot.viewInfo.add_info_line(f'launch reduc {overage} bc fog {numFog} vs pathlen {bot.target_player_gather_path.length}')
                launchTiming -= overage
                gatherSplit -= overage

        if launchTiming < gatherSplit:
            gatherSplit += bot.behavior_launch_timing_offset
            if bot.flanking:
                gatherSplit += bot.behavior_flank_launch_timing_offset
            bot.viewInfo.add_info_line(f'launchTiming was {launchTiming} (pathValueWeight {pathValueWeight}), targetLen {pathLength}, adjusting to be same as gatherSplit {gatherSplit}')
            launchTiming = gatherSplit
        else:
            bot.viewInfo.add_info_line(f'launchTiming {launchTiming} (pathValueWeight {pathValueWeight}), targetLen {pathLength}')

        correction = bot._map.turn % 50
        timings = Timings(cycleDuration, quickExpandSplit, gatherSplit, launchTiming, offset, bot._map.turn + cycleDuration - correction, disallowEnemyGather)
        timings.is_early_flank_launch = isOurPathAMostlyFogAltPath

        if bot.teammate_general is not None and bot.teammate_communicator.is_team_lead and bot.target_player_gather_path is not None and correction < timings.launchTiming and bot._map.turn >= 50:
            bot.send_teammate_communication(
                f'Launch turn {(bot._map.turn + timings.launchTiming - correction) // 2} from here:',
                pingTile=bot.target_player_gather_path.start.tile,
                cooldown=5,
                detectionKey='2v2 launch timings')

        logbook.info(f"Recalculated timings. longSpawns {longSpawns}, Timings {str(timings)}")
        return timings

    @staticmethod
    def get_timings(bot) -> Timings:
        with bot.perf_timer.begin_move_event('GatherAnalyzer scan'):
            bot.gatherAnalyzer.scan()

        if bot.target_player_gather_path is None:
            bot.recalculate_player_paths(force=True)

        countFrOnPath = 0
        countEnOnPath = 0
        countNeutOnPath = 0

        launchTiming = 20
        gatherSplit = 20
        if bot.is_still_ffa_and_non_dominant() and bot.targetPlayer != -1:
            gatherSplit = 32

        timeOutsideLaunchAndGath = 0

        cycle = 50
        expValue = 20.0
        bypass = True
        if bot.expansion_plan is not None and bot.target_player_gather_targets is not None:
            bypass = False
            expValue = bot.expansion_plan.cumulative_econ_value
            for opt in bot.expansion_plan.all_paths:
                if opt.length < 1:
                    continue
                if opt.econValue / opt.length > 0.99 and opt.tileSet.isdisjoint(bot.target_player_gather_targets):
                    timeOutsideLaunchAndGath += opt.length

        if bot.target_player_gather_path is not None:
            for t in bot.target_player_gather_path.tileList:
                if bot._map.is_tile_friendly(t):
                    countFrOnPath += 1
                elif bot._map.is_tile_on_team(t, bot.targetPlayer):
                    countEnOnPath += 1
                elif t.player == -1:
                    countNeutOnPath += 1
            cycle = 50
            if bot.timings is not None:
                cycle = bot.timings.cycleTurns
            launchTiming = cycle - bot.shortest_path_to_target_player.length - 5
            launchTiming += countEnOnPath // 2
            launchTiming += countNeutOnPath // 2
            launchTiming -= countFrOnPath // 2

            xPweight = int(expValue * 0.5)
            minExpWeighted = 32
            expGatherTiming = max(15, min(minExpWeighted, 50 - timeOutsideLaunchAndGath))
            gatherSplit = min(launchTiming, expGatherTiming)
            if not bypass:
                bot.viewInfo.add_info_line(
                    f'timingsBase: g{gatherSplit} <- min(launch {launchTiming}, max(15, min({minExpWeighted}, 50-timeAv {timeOutsideLaunchAndGath} ({50 - timeOutsideLaunchAndGath}))), en{countEnOnPath}, fr{countFrOnPath}, nt{countNeutOnPath}, expW {xPweight}')

        randomVal = random.randint(-2, 2)
        spawnDist = bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation)
        longSpawns = bot.target_player_gather_path is not None and spawnDist > 22
        genPlayer = bot._map.players[bot.general.player]

        gatherSplit = min(gatherSplit, genPlayer.tileCount - countFrOnPath)

        gatherSplit += randomVal

        quickExpandSplit = 0

        if bot.defend_economy:
            gatherSplit += 2

        if bot.currently_forcing_out_of_play_gathers:
            gatherSplit += 2

        if bot.is_still_ffa_and_non_dominant():
            oldGath = gatherSplit
            gatherSplit = 38

            if bot.targetPlayer != -1:
                gatherSplit = 50 - bot.shortest_path_to_target_player.length

            if bot.targetPlayer != -1 and bot.targetPlayerObj.aggression_factor > 150:
                gatherSplit = 50 - bot.shortest_path_to_target_player.length - 4

            bot.info(f'FFA gath split adjust {oldGath} -> {gatherSplit}')

        disallowEnemyGather = False

        tileDiff = bot.opponent_tracker.get_tile_differential()
        if tileDiff < 4:
            back = max(-10, tileDiff // 2) - 2
            if not bypass:
                bot.viewInfo.add_info_line(f'gathSplit/launch back {back} turns due to tileDiff {tileDiff}')
            gatherSplit += back
            launchTiming += back

        if bot.flanking:
            bot.viewInfo.add_info_line(f'gathSplit flanking += {bot.behavior_flank_launch_timing_offset}')
            gatherSplit += bot.behavior_flank_launch_timing_offset
            launchTiming = gatherSplit

        if bot.teammate_path is not None and bot.target_player_gather_path is not None and bot.target_player_gather_path.start.tile == bot.teammate_general:
            gatherSplit -= bot.teammate_path.length // 2 + 2
            launchTiming = gatherSplit

        isOurPathAMostlyFogAltPath = False
        if bot.target_player_gather_path is not None:
            pathCheck = bot.target_player_gather_path
            if pathCheck.length > 25:
                pathCheck = pathCheck.get_subsegment(25)
            numFog = bot.get_undiscovered_count_on_path(pathCheck)
            numEn = bot.get_enemy_count_on_path(pathCheck)
            if numEn > 0 or bot.target_player_gather_path.length < 20:
                overage = 2 * numFog - 1 * pathCheck.length // 2 - numEn
                if overage > 0 and bot._map.turn > 85 and numEn < pathCheck.length // 3:
                    isOurPathAMostlyFogAltPath = True
                    if not bypass:
                        bot.viewInfo.add_info_line(f'launch reduc {overage} bc fog {numFog} vs pathlen {pathCheck.length}')
                    launchTiming -= overage
                    gatherSplit -= overage

        while launchTiming < 0:
            bot.info(f'increasing launch timing {launchTiming} by increasing cycle duration')
            cycle += 50
            launchTiming += 50
            gatherSplit += 50

        if launchTiming < gatherSplit:
            if not bypass:
                bot.viewInfo.add_info_line(f'adjusting launchTiming (was {launchTiming}) to be same as gatherSplit {gatherSplit}, targetLen {bot.shortest_path_to_target_player.length}')
            launchTiming = gatherSplit
        else:
            if not bypass:
                bot.viewInfo.add_info_line(f'launchTiming {launchTiming}, targetLen {bot.shortest_path_to_target_player.length}')

        correction = bot._map.turn % 50
        timings = Timings(cycle, quickExpandSplit, gatherSplit, launchTiming, 0, bot._map.turn + cycle - correction, disallowEnemyGather)
        timings.is_early_flank_launch = isOurPathAMostlyFogAltPath

        logbook.info(f"Recalculated timings. longSpawns {longSpawns}, Timings {str(timings)}")
        return timings
