import typing
import time

import logbook
import DebugHelper


from Algorithms import MapSpanningUtils
import SearchUtils
from Algorithms import WatchmanRouteUtils
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotTargeting import BotTargeting
from BotModules.BotDefense import BotDefense

from BotModules.BotComms import BotComms
from BotModules.BotGatherOps import BotGatherOps
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotRendering import BotRendering
from BotModules.BotRepetition import BotRepetition
from BotModules.BotTimings import BotTimings
from Army import Army
from ArmyEngine import ArmyEngine
from ArmyEngine import ArmySimResult
from ArmyAnalyzer import ArmyAnalyzer
from ArmyTracker import ArmyTracker
from Gather import Gather
from Path import Path
from StrategyModels import ExpansionPotential
from ViewInfo import PathColorer, TargetStyle
from Models.Move import Move
from base.client.map import Tile
from DangerAnalyzer import ThreatType, ThreatObj

class BotCombatOps:
    @staticmethod
    def check_for_king_kills_and_races(bot, threat: ThreatObj | None, force: bool = False) -> typing.Tuple[Move | None, Path | None, float]:
        from BotModules.BotTargeting import BotTargeting

        kingKillPath = None
        kingKillChance = 0.0
        alwaysCheckKingKillWithinRange = 5
        if bot.is_all_in_losing and not bot.all_in_city_behind:
            alwaysCheckKingKillWithinRange = 7

        if BotTargeting.is_ffa_situation(bot):
            alwaysCheckKingKillWithinRange += 3

        extraTurnOnPriority = 0
        if threat is not None and bot._map.player_has_priority_over_other(bot.player.index, threat.threatPlayer, bot._map.turn + threat.turns):
            extraTurnOnPriority = 1

        threatIsGeneralKill = threat is not None and threat.threatType == ThreatType.Kill and threat.path.tail.tile.isGeneral

        enemyGeneral: Tile
        for enemyGeneral in bot.largeTilesNearEnemyKings.keys():
            if enemyGeneral is None or enemyGeneral.player == bot.general.player or enemyGeneral.player in bot._map.teammates:
                continue

            enPlayer = enemyGeneral.player
            if enPlayer == -1:
                enPlayer = bot.targetPlayer
            if enPlayer == -1:
                continue

            altEnGenPositions = bot.alt_en_gen_positions[enPlayer]

            curExtraTurn = extraTurnOnPriority

            turnsToDeath = None
            killRaceCutoff = 0.3
            if threatIsGeneralKill:
                turnsToDeath = threat.turns + 1 + curExtraTurn
                econRatio = bot.opponent_tracker.get_current_econ_ratio()
                killRaceCutoff = min(0.99, 0.95 * econRatio * econRatio)

            thisPlayerDepth = alwaysCheckKingKillWithinRange

            if bot.target_player_gather_path is not None and bot.targetPlayer == enPlayer:
                thisPlayerDepth = min(thisPlayerDepth, bot.target_player_gather_path.length // 3)

            attackNegTiles = set()
            targetArmy = 1

            if not enemyGeneral.visible:
                if not enemyGeneral.isGeneral:
                    pass

            threatDistCutoff = 1000
            if threat is not None:
                threatDistCutoff = threat.turns + curExtraTurn
                if not bot._map.players[threat.threatPlayer].knowsKingLocation:
                    tilesOppHasntSeen = set([
                        t for t in bot.player.tiles
                        if bot._map.get_distance_between(enemyGeneral, t) <= bot.target_player_gather_path.length
                           and bot._map.get_distance_between(bot.general, t) < bot.target_player_gather_path.length // 3
                    ])
                    closeTilesOppHasSeen = set()
                    for tile in bot.armyTracker.tiles_ever_owned_by_player[threat.threatPlayer]:
                        if tile in tilesOppHasntSeen:
                            tilesOppHasntSeen.discard(tile)
                            closeTilesOppHasSeen.add(tile)
                        for adj in tile.adjacents:
                            if adj.player == bot.general.player:
                                if adj in tilesOppHasntSeen:
                                    tilesOppHasntSeen.discard(adj)
                                    closeTilesOppHasSeen.add(adj)

                    unknownsToHunt = len(tilesOppHasntSeen) - len(closeTilesOppHasSeen) - threat.turns
                    if unknownsToHunt > 0:
                        cutoffIncrease = int(unknownsToHunt ** 0.5) - 1
                        if cutoffIncrease > 0:
                            threatDistCutoff += cutoffIncrease

            nonGenArmy = 0
            addlIncrement = 0.0

            if not enemyGeneral.visible:
                defTurns = 0
                optTargetArmy = BotDefense.determine_fog_defense_amount_available_for_tiles(bot, altEnGenPositions, enPlayer, fogDefenseTurns=defTurns, fogReachTurns=5)
                newTargetArmyOption = optTargetArmy

                if enemyGeneral.isGeneral:
                    newTargetArmyOption -= enemyGeneral.army

                if newTargetArmyOption > targetArmy:
                    targetArmy = newTargetArmyOption
                    nonGenArmy = optTargetArmy

                if threat is None and bot.opponent_tracker.get_player_gather_queue(enPlayer).cur_max_tile_size > 2:
                    addlIncrement += 0.5

                logbook.info(f'will attmpt QK en{enPlayer} fog defense in {defTurns}t was {targetArmy}')

            if not enemyGeneral.isGeneral:
                addlIncrement += 0.5
                if not BotTargeting.is_ffa_situation(bot):
                    thisPlayerDepth = max(3, thisPlayerDepth - 5)

            qkDist = 8
            if bot.target_player_gather_path is not None:
                qkDist = 2 * bot.target_player_gather_path.length // 3
            if len(altEnGenPositions) < 20:
                quickKill = SearchUtils.dest_breadth_first_target(
                    bot._map,
                    altEnGenPositions,
                    max(targetArmy, 1),
                    0.05,
                    qkDist,
                    attackNegTiles,
                    bot.general.player,
                    ignoreGoalArmy=bot.has_defenseless_modifier,
                    additionalIncrement=addlIncrement,
                    noLog=True)
                logbook.info(f'QK @{enPlayer} turns {qkDist} for targetArmy {max(1, targetArmy)} addlInc {addlIncrement} returned {quickKill}   --  @ {" | ".join([str(t) for t in altEnGenPositions])},  attackNegs {" | ".join([str(t) for t in attackNegTiles])}')

                if quickKill is not None and quickKill.length > 0:
                    connectedTiles, missingRequired = MapSpanningUtils.get_spanning_tree_from_tile_lists(bot._map, altEnGenPositions, set())
                    additionalKillDist = len(connectedTiles)
                    enemyNegTiles = []
                    if threat is not None:
                        enemyNegTiles.append(threat.path.start.tile)
                        enemyNegTiles.extend(quickKill.tileList)
                    maxEnDefTurns = quickKill.length + additionalKillDist
                    cityLimit = 1
                    if not enemyGeneral.isGeneral:
                        cityLimit += 1

                    cutoffKillArmy = 0
                    cutoffEmergence = 0.4
                    if threatIsGeneralKill:
                        cutoffKillArmy = bot.opponent_tracker.get_approximate_fog_army_risk(enPlayer, cityLimit=None, inTurns=0)
                        if enemyGeneral.isGeneral:
                            cutoffKillArmy -= enemyGeneral.army + quickKill.length // 2
                        cutoffEmergence = 0.15
                    else:
                        bestDef = bot.opponent_tracker.get_approximate_fog_army_risk(enPlayer, cityLimit=None, inTurns=maxEnDefTurns - 3)

                        cutoffKillArmy = bestDef + 2 * additionalKillDist - 5

                    cutoffKillArmy = max(0, cutoffKillArmy)

                    if quickKill.value > cutoffKillArmy or threatIsGeneralKill:
                        logbook.info(f"    quick-kill path val {quickKill.value} > ({cutoffKillArmy} in {maxEnDefTurns}t) found to kill enemy king w/ additionalKillDist {additionalKillDist}? {str(quickKill)}")
                        ogQuickKill = quickKill
                        ogAdditionalKillDist = additionalKillDist
                        if not quickKill.tileList[-1].isGeneral:
                            turns = 30
                            if threat is not None:
                                turns = threat.turns

                            startTile = quickKill.tileList[0]

                            with bot.perf_timer.begin_move_event(f'QK WRP {startTile} tgA {cutoffKillArmy}'):
                                maxTime = 0.020

                                toReveal = BotTargeting.get_target_player_possible_general_location_tiles_sorted(bot, elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=cutoffEmergence, includeCities=False)

                                wrpPath = WatchmanRouteUtils.get_watchman_path(
                                    bot._map,
                                    startTile,
                                    toReveal,
                                    timeLimit=maxTime,
                                )

                            if wrpPath is not None:
                                closest = None
                                closestDist = 100
                                found = False
                                for t in wrpPath.tileList:
                                    dist = bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, t)
                                    if dist < closestDist:
                                        closest = t
                                        closestDist = dist

                                    if not found:
                                        found = True
                                        quickKill = wrpPath

                                if found:
                                    bot.info(f'QK WRP {wrpPath}')
                                    additionalKillDist = closestDist

                                if quickKill != wrpPath:
                                    bot.viewInfo.add_info_line(f'skipped QK wrpPath (addl {additionalKillDist}) was {wrpPath}')

                        killRaceChance = BotCombatOps.get_kill_race_chance(bot, quickKill, enGenProbabilityCutoff=cutoffEmergence + 0.1, turnsToDeath=turnsToDeath, cutoffKillArmy=cutoffKillArmy)
                        if threat is None or not threatIsGeneralKill or killRaceChance >= killRaceCutoff:
                            bot.info(f"QK {quickKill.value} {quickKill.length}t kill race chance {killRaceChance:.3f} > {killRaceCutoff:.2f} with cutoffKillArmy {cutoffKillArmy} in {maxEnDefTurns}t +{additionalKillDist} (turns to death {turnsToDeath}) :^)")
                            bot.viewInfo.color_path(PathColorer(quickKill, 255, 240, 79, 244, 5, 200))
                            move = Move(quickKill.start.tile, quickKill.start.next.tile)
                            if BotPathingUtils.is_move_safe_valid(bot, move):
                                bot.curPath = None
                                if quickKill.start.next.tile.isCity:
                                    bot.curPath = quickKill

                                for t in altEnGenPositions:
                                    bot.viewInfo.add_targeted_tile(t, TargetStyle.RED, radiusReduction=0)

                                if connectedTiles:
                                    for t in connectedTiles:
                                        bot.viewInfo.add_targeted_tile(t, TargetStyle.RED, radiusReduction=8)
                                bot.viewInfo.infoText = f"QK chance {killRaceChance:.2f} {quickKill.value}v > {cutoffKillArmy} in {maxEnDefTurns}t {quickKill.length}t+{additionalKillDist}t :^)"
                                return move, quickKill, killRaceChance
                        elif killRaceChance > kingKillChance:
                            bot.info(f"QK (low chance) {quickKill.value} {quickKill.length}t kill race chance {killRaceChance:.3f} < {killRaceCutoff:.2f} but > kkc {kingKillChance:.2f} (with cutoffKillArmy {cutoffKillArmy} in {maxEnDefTurns}t +{additionalKillDist} (death {turnsToDeath}t) :^(")
                            kingKillPath = quickKill
                            kingKillChance = killRaceChance
                        else:
                            bot.info(f"NO QK {quickKill.value} {quickKill.length}t kill race chance {killRaceChance:.3f} vs cutoff {killRaceCutoff:.2f} with cutoffKillArmy {cutoffKillArmy} in {maxEnDefTurns}t +{additionalKillDist} :(")
                    else:
                        logbook.info(f" ---quick-kill path val {quickKill.value} < {cutoffKillArmy} in {maxEnDefTurns}t {quickKill.length}t+{additionalKillDist}t @enemy king. Low val. {str(quickKill)}")

            if not enemyGeneral.isGeneral and not BotTargeting.is_ffa_situation(bot) and len(altEnGenPositions) > 2:
                continue

            logbook.info(
                f"Performing depth increasing BFS kill search on enemy king {enemyGeneral.toString()} depth {thisPlayerDepth}")
            with bot.perf_timer.begin_move_event(f"race depth increasing vs p{enPlayer} {enemyGeneral}"):
                inc = 1
                for depth in range(2, thisPlayerDepth, inc):
                    enemyNegTiles = []
                    if threat is not None:
                        enemyNegTiles.append(threat.path.start.tile)
                    enemySavePath = BotDefense.get_best_defense(bot, enemyGeneral, depth - 1, enemyNegTiles)
                    defTurnsLeft = depth - 1
                    depthTargetArmy = targetArmy
                    if enemySavePath is not None:
                        defTurnsLeft -= enemySavePath.length
                        depthTargetArmy = max(enemySavePath.value + nonGenArmy, depthTargetArmy)
                        if not enemyGeneral.visible:
                            depthTargetArmy = max(depthTargetArmy, enemySavePath.value + nonGenArmy + BotDefense.determine_fog_defense_amount_available_for_tiles(bot, altEnGenPositions, enPlayer, fogDefenseTurns=defTurnsLeft))
                        logbook.info(f"  targetArmy {targetArmy}, enemySavePath {enemySavePath.toString()}")
                        attackNegTiles = enemySavePath.tileSet.copy()
                        attackNegTiles.remove(enemyGeneral)

                    if not enemyGeneral.visible:
                        depthTargetArmy = max(depthTargetArmy, BotDefense.determine_fog_defense_amount_available_for_tiles(bot, altEnGenPositions, enPlayer, fogDefenseTurns=depth - 1))

                    logbook.info(f"  targetArmy to add to enemyGeneral kill = {depthTargetArmy}")
                    shouldPrioritizeTileCaps = (
                            not BotStateQueries.is_all_in(bot)
                            and not BotTargeting.is_ffa_situation(bot)
                            and (threat is None or threat.threatType != ThreatType.Kill)
                    )
                    killPath = SearchUtils.dest_breadth_first_target(
                        bot._map,
                        altEnGenPositions,
                        max(depthTargetArmy, 1),
                        0.05,
                        depth,
                        attackNegTiles,
                        bot.general.player,
                        dupeThreshold=3,
                        preferCapture=shouldPrioritizeTileCaps,
                        ignoreGoalArmy=bot.has_defenseless_modifier,
                        additionalIncrement=addlIncrement,
                        noLog=True)
                    if killPath is not None and killPath.length > 0:
                        killChance = 0.0
                        if killPath and threatIsGeneralKill:
                            killChance = BotCombatOps.get_kill_race_chance(bot, killPath, enGenProbabilityCutoff=0.3, turnsToDeath=turnsToDeath)
                        logbook.info(f"    depth {depth} path found to kill enemy king? {str(killPath)}")
                        if threat is None or threat.threatType != ThreatType.Kill or (threatDistCutoff >= killPath.length and killChance > killRaceCutoff):
                            logbook.info(f"    DEST BFS K found kill path length {killPath.length} :^)")
                            bot.viewInfo.color_path(PathColorer(killPath, 255, 240, 79, 244, 5, 200))
                            move = Move(killPath.start.tile, killPath.start.next.tile)
                            bot.curPath = None
                            if killPath.start.next.tile.isCity:
                                bot.curPath = killPath
                            if BotPathingUtils.is_move_safe_valid(bot, move):
                                bot.viewInfo.infoText = f"Depth increasing Killpath against general length {killPath.length}"
                                return move, killPath, killChance
                        elif killChance > kingKillChance:
                            bot.info(f"    DEST BFS K (low chance) {killPath.value} {killPath.length}t kill race chance {killChance:.3f} < {killRaceCutoff:.2f}  but > kingKillChance {kingKillChance:.2f} :(")
                            kingKillPath = killPath
                            kingKillChance = killChance
                        else:
                            logbook.info(
                                f"    DEST BFS K found kill path {str(killPath)} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
                            if kingKillPath is None:
                                logbook.info("      saving above kingKillPath as backup in case we can't defend threat")
                                kingKillPath = killPath

                rangeBasedOnDistance = int(BotPathingUtils.distance_from_general(bot, bot.targetPlayerExpectedGeneralLocation) // 3 - 1)
                additionalKillArmyRequirement = 0
                if not enemyGeneral.isGeneral:
                    additionalKillArmyRequirement = bot.opponent_tracker.get_approximate_fog_army_risk(enPlayer, cityLimit=None, inTurns=0)
                additionalKillArmyRequirement = max(0, additionalKillArmyRequirement)

                if not force and (not bot.opponent_tracker.winning_on_army(byRatio=1.3)
                                  and not bot.opponent_tracker.winning_on_army(byRatio=1.3, againstPlayer=bot.targetPlayer)
                                  and not BotStateQueries.is_all_in(bot)
                                  and not enemyGeneral.visible):
                    rangeBasedOnDistance = int(BotPathingUtils.distance_from_general(bot, bot.targetPlayerExpectedGeneralLocation) // 4 - 1)

                    additionalKillArmyRequirement = bot.opponent_tracker.get_approximate_fog_army_risk(enPlayer, cityLimit=None, inTurns=3)
                    logbook.info(f'additional kill army requirement is currently {additionalKillArmyRequirement}')

                depth = max(alwaysCheckKingKillWithinRange, rangeBasedOnDistance)

                if bot.is_all_in_losing or BotTargeting.is_ffa_situation(bot):
                    depth += 5

                logbook.info(f"Performing depth {depth} BFS kill search on enemy kings")
                fullKillReq = targetArmy + additionalKillArmyRequirement
                killPath = SearchUtils.dest_breadth_first_target(bot._map, altEnGenPositions, fullKillReq, 0.05, depth, attackNegTiles, bot.general.player, False, 3)
                killChance = 0.0
                if killPath:
                    killChance = BotCombatOps.get_kill_race_chance(bot, killPath, enGenProbabilityCutoff=0.3, turnsToDeath=turnsToDeath)
                if (killPath is not None and killPath.length >= 0) and (threat is None or threat.threatType != ThreatType.Kill or (threatDistCutoff >= killPath.length and killChance > killRaceCutoff)):
                    logbook.info(f"DBFT d{depth} for {fullKillReq}a found kill path length {killPath.length} :^)")
                    bot.curPath = None
                    bot.viewInfo.color_path(PathColorer(killPath, 200, 100, 0))
                    move = Move(killPath.start.tile, killPath.start.next.tile)

                    if BotPathingUtils.is_move_safe_valid(bot, move):
                        bot.info(f"DBFT d{depth} K for {fullKillReq}a: {killPath.length}t {killPath.value}v  (a = tg{targetArmy} + addl{additionalKillArmyRequirement}) force {str(force)[0]}")
                        return move, killPath, killChance

                elif killChance > kingKillChance:
                    bot.info(f"DBFT d{depth} for {fullKillReq}a (low chance) {killPath.value} {killPath.length}t kill race chance {killChance:.3f} < {killRaceCutoff:.2f} but > kingKillChance {kingKillChance:.2f} :(")
                    kingKillPath = killPath
                    kingKillChance = killChance
                elif killPath is not None and killPath.length > 0:
                    logbook.info(
                        f"DEST BFS K found kill path {str(killPath)} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
                    if kingKillPath is None:
                        logbook.info("  saving above kingKillPath as backup in case we can't defend threat")

                        kingKillPath = killPath

            if BotTargeting.is_ffa_situation(bot):
                tiles = bot.largeTilesNearEnemyKings[enemyGeneral]
                if len(tiles) > 0:
                    logbook.info(f"Attempting to find A_STAR kill path against general {enemyGeneral.player} ({enemyGeneral})")
                    bestTurn = 1000
                    bestPath = None
                    targets = set(altEnGenPositions)
                    path = SearchUtils.a_star_kill(
                        bot._map,
                        tiles,
                        targets,
                        0.03,
                        BotPathingUtils.distance_from_general(bot, bot.targetPlayerExpectedGeneralLocation) // 4,
                        requireExtraArmy=targetArmy + additionalKillArmyRequirement,
                        negativeTiles=attackNegTiles)

                    killChance = 0.0
                    if killPath:
                        killChance = BotCombatOps.get_kill_race_chance(bot, killPath, enGenProbabilityCutoff=0.3, turnsToDeath=turnsToDeath)

                    if (path is not None and path.length >= 0) and (threat is None or threat.threatType != ThreatType.Kill or ((threatDistCutoff >= path.length or BotStateQueries.is_all_in(bot)) and threat.threatPlayer == enemyGeneral.player and killChance > killRaceCutoff)):
                        logbook.info(f"  A_STAR found kill path length {path.length} :^)")
                        bot.viewInfo.color_path(PathColorer(path, 174, 4, 214, 255, 10, 200))
                        bot.curPath = path.get_subsegment(2)
                        bot.curPathPrio = 5
                        if path.length < bestTurn:
                            bestPath = path
                            bestTurn = path.length
                    elif path is not None and path.length > 0:
                        logbook.info(f"  A_STAR found kill path {str(path)} BUT ITS LONGER THAN OUR THREAT LENGTH :(")
                        bot.viewInfo.color_path(PathColorer(path, 114, 4, 194, 255, 20, 100))
                        if kingKillPath is None:
                            logbook.info("    saving above kingKillPath as backup in case we can't defend threat")
                            kingKillPath = path
                    if bestPath is not None:
                        bot.info(f"A* Killpath! {enemyGeneral.toString()},  {bestPath.toString()}")
                        move = Move(bestPath.start.tile, bestPath.start.next.tile)
                        return move, path, killChance

        return None, kingKillPath, kingKillChance

    @staticmethod
    def get_army_scrim_move(
            bot,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            friendlyHasKillThreat: bool | None = None,
            forceKeepMove=False
    ) -> Move | None:
        friendlyPath, enemyPath, result = BotCombatOps.get_army_scrim_paths(
            bot,
            friendlyArmyTile,
            enemyArmyTile,
            friendlyHasKillThreat=friendlyHasKillThreat)
        if friendlyPath is not None and friendlyPath.length > 0:
            firstPathMove = BotPathingUtils.get_first_path_move(bot, friendlyPath)
            if (
                    firstPathMove
                    and not result.best_result_state.captured_by_enemy
                    and (result.net_economy_differential > bot.engine_mcts_move_estimation_net_differential_cutoff or forceKeepMove)
            ):
                bot.info(f'ARMY SCRIM MOVE {str(friendlyArmyTile)}@{str(enemyArmyTile)} EVAL {str(result)}: {str(firstPathMove)}')

                return firstPathMove

        return None

    @staticmethod
    def get_kill_race_chance(bot, generalHuntPath: Path, enGenProbabilityCutoff: float = 0.4, turnsToDeath: int | None = None, cutoffKillArmy: int = 0, againstPlayer: int = None) -> float:
        if generalHuntPath is None:
            return 0.0

        if againstPlayer is None:
            againstPlayer = bot.targetPlayer

        toReveal = BotTargeting.get_target_player_possible_general_location_tiles_sorted(bot, elimNearbyRange=0, player=againstPlayer, cutoffEmergenceRatio=enGenProbabilityCutoff, includeCities=False)
        if not toReveal:
            return 0.0
        for t in toReveal:
            BotRendering.mark_tile(bot, t, alpha=50)

        isOnlyOneSpot = toReveal[0].isGeneral

        if isOnlyOneSpot:
            if turnsToDeath is None:
                return 1.0
            if generalHuntPath.length < turnsToDeath:
                logbook.info(f'We win the race, {generalHuntPath.length}t vs turnsToDeath {turnsToDeath}t')
                return 1.0

            logbook.info(f'We lose the race, {generalHuntPath.length}t vs turnsToDeath {turnsToDeath}t')
            return 0.0

        revealedCount, maxKillTurns, minKillTurns, avgKillTurns, rawKillDistByTileMatrix, bestRevealedPath = WatchmanRouteUtils.get_revealed_count_and_max_kill_turns_and_positive_path(bot._map, generalHuntPath, toReveal, cutoffKillArmy=cutoffKillArmy)

        if bestRevealedPath is None:
            killChance = 0.0
            bot.info(f'KillRaceProb {killChance:.2f} - NO rev {revealedCount} {generalHuntPath} -- min{minKillTurns} max{maxKillTurns} avg{avgKillTurns:.1f}')
            return killChance

        killChance = revealedCount / len(toReveal)
        if turnsToDeath is None:
            bot.info(f'KillRaceProb {killChance:.2f} - {bestRevealedPath.length}t ({generalHuntPath.length}t) revealed {revealedCount}/{len(toReveal)}, kill min{minKillTurns} max{maxKillTurns} avg{avgKillTurns:.1f}')
            return killChance

        sumKill = 0.0
        sumTotal = 0.0
        reachedCount = 0
        tooFarToKillTiles = []
        for tile in toReveal:
            emgVal = 1 + bot.armyTracker.get_tile_emergence_for_player(tile, bot.targetPlayer)
            sumTotal += emgVal
            killDist = rawKillDistByTileMatrix.raw[tile.tile_index]
            if killDist < turnsToDeath:
                sumKill += emgVal
                reachedCount += 1
            else:
                tooFarToKillTiles.append(tile)
                logbook.info(f'{tile} too far to kill {killDist}/{turnsToDeath}, wed lose! :(')

        if sumTotal == 0.0:
            bot.info(f'SUM TOTAL WAS ZERO? THIS SHOULD NEVER HAPPEN')
            return 0.0

        killInTurnsChance = sumKill / sumTotal
        bot.info(f'KillRaceProb {killInTurnsChance:.2f} ({killChance:.2f}) - {bestRevealedPath.length}t ({generalHuntPath.length}t) reached {reachedCount} rev {revealedCount}/{len(toReveal)}, kill min{minKillTurns} max{maxKillTurns} avg{avgKillTurns:.1f}. death in {turnsToDeath}t')
        if tooFarToKillTiles:
            bot.info(f' too far tiles {" | ".join([str(t) for t in tooFarToKillTiles])}')

        return killInTurnsChance

    @staticmethod
    def get_army_scrim_paths(
            bot,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            enemyCannotMoveAway: bool = True,
            friendlyHasKillThreat: bool | None = None
    ) -> typing.Tuple[Path | None, Path | None, ArmySimResult]:
        """
        Returns None for the path WHEN THE FIRST MOVE THE ENGINE WANTS TO MAKE INCLUDES A NO-OP.
        NOTE, These paths should not be executed as paths, they may contain removed-no-ops.

        @param friendlyArmyTile:
        @param enemyArmyTile:
        @param enemyCannotMoveAway:
        @param friendlyHasKillThreat: whether friendly tile is a kill threat against enemy or not. If not provided, will be calculated via a_star
        @return:
        """
        result = BotCombatOps.get_army_scrim_result(bot, friendlyArmyTile, enemyArmyTile, enemyCannotMoveAway=enemyCannotMoveAway, friendlyHasKillThreat=friendlyHasKillThreat)

        if result.best_result_state.captured_by_enemy:
            bot.viewInfo.add_info_line(f'scrim thinks enemy kills us :/ {str(result.expected_best_moves)}')
            return None, None, result

        if result.best_result_state.captures_enemy:
            bot.viewInfo.add_info_line(f'scrim thinks we kill!? {str(result.expected_best_moves)} TODO implement race checks')
            return None, None, result

        if len(result.expected_best_moves) == 0:
            bot.viewInfo.add_info_line(f'scrim returned no moves..? {str(result.expected_best_moves)}')
            return None, None, result

        friendlyPath, enemyPath = BotCombatOps.extract_engine_result_paths_and_render_sim_moves(bot, result)

        return friendlyPath, enemyPath, result

    @staticmethod
    def get_all_in_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if BotStateQueries.is_all_in(bot, ):
            hitGeneralInTurns = bot.all_in_army_advantage_cycle - bot.all_in_army_advantage_counter % bot.all_in_army_advantage_cycle
            if bot.is_all_in_army_advantage and bot.targetPlayerObj.tileCount < 90:
                hitGeneralInTurns = hitGeneralInTurns % 25 + 5
            flankAllInMove = BotCombatOps.try_find_flank_all_in(bot, hitGeneralInTurns)

            if flankAllInMove:
                bot.all_in_army_advantage_counter += 1
                return flankAllInMove

            targets = [bot.targetPlayerExpectedGeneralLocation]

            andTargs = ''

            if not bot.targetPlayerExpectedGeneralLocation.isGeneral:
                andTargs = f' (and undisc)'
                emergenceTiles = BotTargeting.get_target_player_possible_general_location_tiles_sorted(bot, elimNearbyRange=5, cutoffEmergenceRatio=0.6)[0:3]
                targets = emergenceTiles[0:5]
                for t in targets:
                    bot.viewInfo.add_targeted_tile(t, TargetStyle.WHITE)

            if (bot.is_all_in_army_advantage or bot.all_in_city_behind) and not BotStateQueries.is_still_ffa_and_non_dominant(bot):
                andTargs = ' (and cities)'
                if bot.all_in_city_behind or bot._map.remainingPlayers == 2:
                    targets.extend(bot.targetPlayerObj.cities)

            msg = f'allin g AT tg gen{andTargs}, {hitGeneralInTurns}t, {str([str(t) for t in targets])}'

            with bot.perf_timer.begin_move_event(f'pcst {msg}. self.all_in_army_advantage_cycle {bot.all_in_army_advantage_cycle}, self.all_in_army_advantage_counter {bot.all_in_army_advantage_counter}'):
                gathNeg = defenseCriticalTileSet.copy()
                citiesToHalf = set()
                if bot.is_all_in_army_advantage:
                    for contestedCity in bot.cityAnalyzer.owned_contested_cities:
                        if contestedCity.army > bot.targetPlayerObj.standingArmy:
                            citiesToHalf.add(contestedCity)
                        else:
                            gathNeg.add(contestedCity)

                gathCapPlan = Gather.gather_approximate_turns_to_tiles(
                    bot._map,
                    rootTiles=targets,
                    approximateTargetTurns=hitGeneralInTurns,
                    asPlayer=bot.general.player,
                    gatherMatrix=None,
                    captureMatrix=None,
                    negativeTiles=gathNeg,
                    skipTiles=None,
                    prioritizeCaptureHighArmyTiles=False,
                    useTrueValueGathered=True,
                    includeGatherPriorityAsEconValues=True,
                    includeCapturePriorityAsEconValues=True,
                    timeLimit=min(0.075, BotTimings.get_remaining_move_time(bot, )),
                    logDebug=False,
                    viewInfo=bot.viewInfo if bot.info_render_gather_values else None)
                if gathCapPlan is None:
                    return None

                move = gathCapPlan.get_first_move()
                bot.curPath = gathCapPlan
                bot.info(f'PCST ALL IN appx {hitGeneralInTurns}t: {gathCapPlan}')

            if move is not None:
                bot.info(msg)
                if hitGeneralInTurns > 15 and not bot.is_winning_gather_cyclic and not bot.is_all_in_army_advantage:
                    BotComms.send_teammate_communication(bot, f'All in here, hit in {hitGeneralInTurns} moves', detectionKey='allInAtGenTargets', cooldown=10)

                for target in targets:
                    BotComms.send_teammate_tile_ping(bot, target, cooldown=25, cooldownKey=f'allIn{str(target)}')

                bot.all_in_army_advantage_counter += 1
                bot.gatherNodes = gathCapPlan.root_nodes
                return move

        return None

    @staticmethod
    def get_army_scrim_result(
            bot,
            friendlyArmyTile: Tile,
            enemyArmyTile: Tile,
            enemyCannotMoveAway: bool = False,
            enemyHasKillThreat: bool | None = None,
            friendlyHasKillThreat: bool | None = None,
            friendlyPrecomputePaths: typing.List[Move | None] | None = None
    ) -> ArmySimResult:
        frArmies = [BotStateQueries.get_army_at(bot, friendlyArmyTile)]
        enArmies = [BotStateQueries.get_army_at(bot, enemyArmyTile)]

        if bot.engine_use_mcts and bot.engine_force_multi_tile_mcts:
            # frTiles = bot.find_large_tiles_near(
            #     fromTiles=[friendlyArmyTile, enemyArmyTile],
            #     distance=bot.engine_army_nearby_tiles_range,
            #     forPlayer=bot.general.player,
            #     allowGeneral=True,
            #     limit=bot.engine_mcts_scrim_armies_per_player_limit,
            #     minArmy=6,
            # )
            frTiles = []
            # enTiles = bot.find_large_tiles_near(
            #     fromTiles=[friendlyArmyTile, enemyArmyTile],
            #     distance=bot.engine_army_nearby_tiles_range,
            #     forPlayer=enemyArmyTile.player,
            #     allowGeneral=True,
            #     limit=bot.engine_mcts_scrim_armies_per_player_limit - 1,
            #     minArmy=6,
            # )
            enTiles = []

            for frTile in frTiles:
                if frTile != friendlyArmyTile:
                    frArmies.append(BotStateQueries.get_army_at(bot, frTile))
                    bot.viewInfo.add_targeted_tile(frTile, TargetStyle.TEAL)

            for enTile in enTiles:
                if enTile != enemyArmyTile:
                    enArmies.append(BotStateQueries.get_army_at(bot, enTile))
                    bot.viewInfo.add_targeted_tile(enTile, TargetStyle.PURPLE)

            lastMove: Move | None = bot.armyTracker.lastMove
            if bot.engine_always_include_last_move_tile_in_scrims and lastMove is not None:
                if lastMove.dest.player == bot.general.player and lastMove.dest.army > 1:
                    lastMoveArmy = BotStateQueries.get_army_at(bot, lastMove.dest)
                    if lastMoveArmy not in frArmies:
                        frArmies.append(lastMoveArmy)

        result = BotCombatOps.get_armies_scrim_result(
            bot,
            friendlyArmies=frArmies,
            enemyArmies=enArmies,
            enemyCannotMoveAway=enemyCannotMoveAway,
            enemyHasKillThreat=enemyHasKillThreat,
            friendlyHasKillThreat=friendlyHasKillThreat,
            friendlyPrecomputePaths=friendlyPrecomputePaths,
        )
        return result

    @staticmethod
    def get_armies_scrim_result(
            bot,
            friendlyArmies: typing.List[Army],
            enemyArmies: typing.List[Army],
            enemyCannotMoveAway: bool = False,
            enemyHasKillThreat: bool | None = None,
            friendlyHasKillThreat: bool | None = None,
            time_limit: float = 0.05,
            friendlyPrecomputePaths: typing.List[Move | None] | None = None
    ) -> ArmySimResult:
        if len(friendlyArmies) == 0 or len(enemyArmies) == 0:
            return ArmySimResult()

        result = BotCombatOps.get_scrim_cached(bot, friendlyArmies, enemyArmies)
        if result is not None:
            bot.info(
                f'  ScC {"+".join([str(a.tile) for a in friendlyArmies])}@{"+".join([str(a.tile) for a in enemyArmies])}: {str(result)} {repr(result.expected_best_moves)}')
            return result

        if friendlyHasKillThreat is None:
            friendlyHasKillThreat = False
            for frArmy in friendlyArmies:
                friendlyArmyTile = frArmy.tile
                targets = set()
                targets.add(bot.targetPlayerExpectedGeneralLocation)
                path = SearchUtils.a_star_kill(
                    bot._map,
                    [friendlyArmyTile],
                    targets,
                    0.03,
                    BotPathingUtils.distance_from_general(bot, bot.targetPlayerExpectedGeneralLocation) // 3,
                    # self.general_safe_func_set,
                    requireExtraArmy=5 if bot.targetPlayerExpectedGeneralLocation.isGeneral else 20,
                    negativeTiles=set([a.tile for a in enemyArmies]))
                if path is not None:
                    friendlyHasKillThreat = True

        if enemyHasKillThreat is None:
            enemyHasKillThreat = False
            for enArmy in enemyArmies:
                for path in enArmy.expectedPaths:
                    if path is not None and path.tail.tile.isGeneral and bot._map.is_tile_friendly(path.tail.tile):
                        if path.calculate_value(enArmy.player, teams=bot._map.team_ids_by_player_index, negativeTiles=set([a.tile for a in friendlyArmies])) > 0:
                            enemyHasKillThreat = True

        if len(enemyArmies) == 0:
            enemyArmies = [bot.get_army_at(bot._map.players[bot.targetPlayer].tiles[0])]

        engine: ArmyEngine = ArmyEngine(bot._map, friendlyArmies, enemyArmies, bot.board_analysis, timeCap=0.05, mctsRunner=bot.mcts_engine)
        engine.eval_params = bot.mcts_engine.eval_params
        engine.allow_enemy_no_op = bot.engine_allow_enemy_no_op
        engine.honor_mcts_expected_score = bot.engine_honor_mcts_expected_score
        engine.honor_mcts_expanded_expected_score = bot.engine_honor_mcts_expanded_expected_score
        if bot.engine_include_path_pre_expansion:
            engine.forced_pre_expansions = []
            for enArmy in enemyArmies:
                altPaths = ArmyTracker.get_army_expected_path(bot._map, enArmy, bot.general, bot.armyTracker.player_targets)
                for enPath in enArmy.expectedPaths:
                    if enPath is not None:
                        engine.forced_pre_expansions.append(enPath.get_subsegment(bot.engine_path_pre_expansion_cutoff_length).convert_to_move_list())
                    matchAlt = None
                    for altPath in list(altPaths):
                        if altPath is None or altPath.tail.tile == enPath.tail.tile:
                            altPaths.remove(altPath)
                for altPath in altPaths:
                    engine.forced_pre_expansions.append(altPath.get_subsegment(bot.engine_path_pre_expansion_cutoff_length).convert_to_move_list())
            for frArmy in friendlyArmies:
                for frPath in frArmy.expectedPaths:
                    if frPath is not None:
                        engine.forced_pre_expansions.append(frPath.get_subsegment(bot.engine_path_pre_expansion_cutoff_length).convert_to_move_list())
            if friendlyPrecomputePaths is not None:
                engine.forced_pre_expansions.extend([p[0:bot.engine_path_pre_expansion_cutoff_length] for p in friendlyPrecomputePaths])

        depth = 4
        enemyArmy = enemyArmies[0]
        if enemyCannotMoveAway and bot.engine_allow_force_incoming_armies_towards:
            depth = 6
            if len(enemyArmy.expectedPaths) > 0:
                engine.force_enemy_towards = SearchUtils.build_distance_map_matrix(bot._map, [enemyArmy.expectedPaths[0].tail.tile])
                logbook.info(f'forcing enemy scrim moves towards {str(enemyArmy.expectedPaths[0].tail.tile)}')
            else:
                engine.force_enemy_towards_or_parallel_to = SearchUtils.build_distance_map_matrix(bot._map, [bot.general])
                logbook.info(f'forcing enemy scrim moves towards our general')

            engine.allow_enemy_no_op = False

        if DebugHelper.IS_DEBUGGING:
            engine.time_limit = 1000
            engine.iteration_limit = 1000
        else:
            engine.time_limit = time_limit
            depthInMove = bot.perf_timer.get_elapsed_since_update(bot._map.turn)
            if depthInMove > 0.15:
                engine.time_limit = 0.06
            if depthInMove > 0.25:
                engine.time_limit = 0.04
            if depthInMove > 0.3:
                engine.time_limit = 0.02

        engine.friendly_has_kill_threat = friendlyHasKillThreat
        engine.enemy_has_kill_threat = enemyHasKillThreat and not BotDefense.should_abandon_king_defense(bot, )
        if bot.disable_engine:
            depth = 0
            engine.time_limit = 0.00001

        result = engine.scan(depth, noThrow=True, mcts=bot.engine_use_mcts)
        bot.info(f' Scr {"+".join([str(a.tile) for a in friendlyArmies])}@{"+".join([str(a.tile) for a in enemyArmies])}: {str(result)} {repr(result.expected_best_moves)}')
        scrimCacheKey = BotCombatOps.get_scrim_cache_key(bot, friendlyArmies, enemyArmies)
        bot.cached_scrims[scrimCacheKey] = result
        if bot.disable_engine:
            result.net_economy_differential = -50.0
            result.best_result_state.tile_differential = -50
        return result

    @staticmethod
    def extend_interspersed_path_moves(bot, paths: typing.List[Path], move: Move | None):
        if move is not None:
            if move.dest is None:
                raise AssertionError()

            curPath: Path | None = None
            for p in paths:
                if p.tail is not None and p.tail.tile == move.source:
                    curPath = p
                    break

            if curPath is None:
                curPath = Path()
                curPath.add_next(move.source)
                paths.append(curPath)
            curPath.add_next(move.dest, move.move_half)

    @staticmethod
    def extract_engine_result_paths_and_render_sim_moves(bot, result: ArmySimResult) -> typing.Tuple[Path | None, Path | None]:
        friendlyPaths: typing.List[Path] = []
        enemyPaths: typing.List[Path] = []

        for friendlyMove, enemyMove in result.expected_best_moves:
            BotCombatOps.extend_interspersed_path_moves(bot, friendlyPaths, friendlyMove)
            BotCombatOps.extend_interspersed_path_moves(bot, enemyPaths, enemyMove)

        friendlyPath: Path | None = None
        enemyPath: Path | None = None
        i = 0
        for path in friendlyPaths:
            if result.expected_best_moves[0][0] is not None and path.start.tile == result.expected_best_moves[0][0].source:
                friendlyPath = path
            else:
                bot.viewInfo.color_path(PathColorer(path, 15, max(0, 255 - 40 * i), 105, max(50, 160 - 20 * i)))
            i += 1
        i = 0
        for path in enemyPaths:
            if result.expected_best_moves[0][1] is not None and path.start.tile == result.expected_best_moves[0][1].source:
                enemyPath = path
            else:
                bot.viewInfo.color_path(PathColorer(path, 105, 0, max(0, 255 - 40 * i), max(50, 160 - 20 * i)))
            i += 1

        if friendlyPath is None or friendlyPath.length == 0:
            friendlyPath = None
        else:
            bot.viewInfo.color_path(PathColorer(friendlyPath, 40, 255, 165, 255))

        if enemyPath is None or enemyPath.length == 0:
            enemyPath = None
        else:
            bot.viewInfo.color_path(PathColorer(enemyPath, 175, 0, 255, 255))

        if len(result.expected_best_moves) > 0:
            if result.expected_best_moves[0][0] is None:
                friendlyPath = None
            if result.expected_best_moves[0][1] is None:
                enemyPath = None

        return friendlyPath, enemyPath

    @staticmethod
    def try_find_counter_army_scrim_path_killpath(
            bot,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> Path | None:
        path, simResult = BotCombatOps.try_find_counter_army_scrim_path_kill(bot, threatPath, allowGeneral=allowGeneral, forceEnemyTowardsGeneral=forceEnemyTowardsGeneral)
        return path

    @staticmethod
    def try_find_counter_army_scrim_path_kill(
            bot,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> typing.Tuple[Path | None, ArmySimResult | None]:
        if threatPath.start.tile.army < 4:
            logbook.info('fuck off, dont try to scrim against tiny tiles idiot')
            return None, None
        friendlyPath, simResult = BotCombatOps.try_find_counter_army_scrim_path(bot, threatPath, allowGeneral, forceEnemyTowardsGeneral=forceEnemyTowardsGeneral)
        if simResult is not None and friendlyPath is not None:
            armiesIntercept = simResult.best_result_state.kills_all_enemy_armies
            if not armiesIntercept:
                sourceThreatDist = bot._map.euclidDist(friendlyPath.start.tile.x, friendlyPath.start.tile.y, threatPath.start.tile.x, threatPath.start.tile.y)
                destThreatDist = bot._map.euclidDist(friendlyPath.start.next.tile.x, friendlyPath.start.next.tile.y, threatPath.start.tile.x, threatPath.start.tile.y)
                if destThreatDist < sourceThreatDist:
                    armiesIntercept = True

            if friendlyPath is not None and armiesIntercept and not simResult.best_result_state.captured_by_enemy:
                bot.info(f'CnASPaK EVAL {str(simResult)}: {str(friendlyPath)}')
                bot.targetingArmy = bot.get_army_at(threatPath.start.tile)
                return friendlyPath, simResult

        return None, None

    @staticmethod
    def try_find_counter_army_scrim_path(
            bot,
            threatPath: Path,
            allowGeneral: bool,
            forceEnemyTowardsGeneral: bool = False
    ) -> typing.Tuple[Path | None, ArmySimResult | None]:
        """
        Sometimes the best sim output involves no-opping one of the tiles. In that case,
        this will return a None path as the best ArmySimResult output. It should be honored, and this tile
        tracked as a scrimming tile, even though the tile should not be moved this turn.

        @param threatPath:
        @param allowGeneral:
        @return:
        """
        threatTile = threatPath.start.tile
        threatDist = BotPathingUtils.distance_from_general(bot, threatTile)
        threatArmy = BotStateQueries.get_army_at(bot, threatTile)
        threatArmy.include_path(threatPath)

        # largeTilesNearTarget = SearchUtils.where(BotCombatOps.find_large_tiles_near(
        #     bot,
        #     fromTiles=threatPath.tileList[0:3],
        #     distance=bot.engine_army_nearby_tiles_range,
        #     limit=bot.engine_mcts_scrim_armies_per_player_limit,
        #     forPlayer=bot.general.player,
        #     allowGeneral=allowGeneral,
        #     addlFilterFunc=lambda t, dist: BotPathingUtils.distance_from_general(bot, t) <= threatDist + 1,
        #     minArmy=max(3, min(15, threatPath.value // 2))
        # ), lambda t: bot.territories.is_tile_in_enemy_territory(t))
        largeTilesNearTarget = []

        bestPath: Path | None = None
        bestSimRes: ArmySimResult | None = None
        if not bot.engine_use_mcts:
            for largeTile in largeTilesNearTarget:
                if largeTile in threatPath.tileSet and largeTile.army < threatPath.value:
                    continue
                with bot.perf_timer.begin_move_event(f'BfScr {str(largeTile)}@{str(threatTile)}'):
                    friendlyPath, enemyPath, simResult = BotCombatOps.get_army_scrim_paths(bot, largeTile, enemyArmyTile=threatTile, enemyCannotMoveAway=True)
                if bestSimRes is None or bestSimRes.best_result_state.calculate_value_int() < simResult.best_result_state.calculate_value_int():
                    bestPath = friendlyPath
                    bestSimRes = simResult
        elif len(largeTilesNearTarget) > 0:
            enTiles = BotCombatOps.find_large_tiles_near(
                bot,
                fromTiles=threatPath.tileList,
                distance=bot.engine_army_nearby_tiles_range,
                forPlayer=threatArmy.player,
                allowGeneral=True,
                limit=bot.engine_mcts_scrim_armies_per_player_limit,
                minArmy=3,
            )

            frArmies: typing.List[Army] = []
            enArmies: typing.List[Army] = []
            for frTile in largeTilesNearTarget:
                frArmies.append(bot.get_army_at(frTile))
                bot.viewInfo.add_targeted_tile(frTile, TargetStyle.GOLD)

            for enTile in enTiles:
                enArmies.append(bot.get_army_at(enTile))
                bot.viewInfo.add_targeted_tile(enTile, TargetStyle.PURPLE)

            with bot.perf_timer.begin_move_event(f'Scr {"+".join([str(largeTile) for largeTile in largeTilesNearTarget])}@{"+".join([str(enTile) for enTile in enTiles])}'):
                simResult = BotCombatOps.get_armies_scrim_result(
                    bot,
                    frArmies,
                    enArmies,
                    enemyCannotMoveAway=forceEnemyTowardsGeneral,
                    # enemyHasKillThreat=True,
                    time_limit=0.07)

                friendlyPath, enemyPath = BotCombatOps.extract_engine_result_paths_and_render_sim_moves(bot, simResult)

            if bestSimRes is None:
                bestPath = friendlyPath
                bestSimRes = simResult

        if len(largeTilesNearTarget) == 0:
            logbook.info(f'No large tiles in range of {str(threatTile)} :/')

        return bestPath, bestSimRes

    @staticmethod
    def find_large_tiles_near(
            bot,
            fromTiles: typing.List[Tile],
            distance: int,
            forPlayer=-2,
            allowGeneral: bool = True,
            limit: int = 5,
            minArmy: int = 10,
            addlFilterFunc: typing.Callable[[Tile, int], bool] | None = None,
            allowTeam: bool = False
    ) -> typing.List[Tile]:
        """
        Returns [limit] largest fromTiles for [forPlayer] within [distance] of [fromTiles]. Excludes generals unless allowGeneral is true.
        Returns them in order from largest army to smallest army.

        @param fromTiles:
        @param distance:
        @param forPlayer:
        @param allowGeneral:
        @param limit:
        @param minArmy:
        @param addlFilterFunc: None or func(tile, dist) should return False to exclude a tile, True to include it. Tile must STILL meet all the other restrictions.
        @return:
        """
        largeTilesNearTargets = []
        if forPlayer == -2:
            forPlayer = bot.general.player

        forPlayers = [forPlayer]
        if allowTeam:
            forPlayers = bot.opponent_tracker.get_team_players_by_player(forPlayer)

        def tile_finder(tile: Tile, dist: int):
            if (tile.player in forPlayers
                    and tile.army > minArmy
                    and (addlFilterFunc is None or addlFilterFunc(tile, dist))
                    and (not tile.isGeneral or allowGeneral)
            ):
                largeTilesNearTargets.append(tile)

        SearchUtils.breadth_first_foreach_dist_fast_incl_neut_cities(bot._map, fromTiles, distance, foreachFunc=tile_finder)

        largeTilesNearTargets = [t for t in sorted(largeTilesNearTargets, key=lambda t: t.army, reverse=True)]

        return largeTilesNearTargets[0:limit]

    @staticmethod
    def continue_killing_target_army(bot) -> Move | None:
        if bot.targetingArmy.tile in bot.armyTracker.armies:
            army = bot.armyTracker.armies[bot.targetingArmy.tile]

            inExpPlan = True
            expPath = None
            if bot.expansion_plan is not None:
                inExpPlan = False
                for path in bot.expansion_plan.all_paths:
                    if bot.targetingArmy.tile in path.tileSet:
                        inExpPlan = True
                        expPath = path
                        bot.viewInfo.add_info_line(f'TargetingArmy was in exp plan as {str(path)}')
                        break

            if not inExpPlan:
                gatherDepth = 10
                threats = [ThreatObj(p.length - 1, p.value, p, ThreatType.Kill) for p in bot.targetingArmy.expectedPaths]
                if len(threats) > 0:
                    with bot.perf_timer.begin_move_event(f'NEW INTERCEPT CONT @{str(bot.targetingArmy)}'):
                        plan = bot.army_interceptor.get_interception_plan(threats, turnsLeftInCycle=bot.timings.get_turns_left_in_cycle(bot._map.turn))
                        if plan is not None:
                            bestOpt = None
                            bestOptAmt = 0
                            bestTurn = 0
                            bestOptAmtPerTurn = 0
                            for turn, option in plan.intercept_options.items():
                                val = option.econValue
                                path = option.path
                                valPerTurn = val / max(1, turn)
                                if path.length < gatherDepth and valPerTurn > bestOptAmtPerTurn:
                                    logbook.info(f'NEW BEST INTERCEPT OPT {str(option)}')
                                    bestOpt = path
                                    bestOptAmt = val
                                    bestTurn = turn
                                    bestOptAmtPerTurn = valPerTurn

                            if bestOpt is not None:
                                move = BotPathingUtils.get_first_path_move(bot, bestOpt)
                                bot.info(f'INTERCEPT {bestOptAmt}v/{bestTurn}t @ {str(bot.targetingArmy)}: {move} -- {str(bestOpt)}')
                                if bot.info_render_intercept_data:
                                    BotRendering.render_intercept_plan(bot, plan)
                                    bot.viewInfo.color_path(PathColorer(bestOpt, 80, 200, 0, alpha=150))
                                return move

                bot.viewInfo.add_info_line(f'stopped targeting army {str(bot.targetingArmy)} because not in expansion plan')
                bot.targetingArmy = None
                return None
            else:
                move = BotPathingUtils.get_euclid_shortest_from_tile_towards_target(bot, expPath.get_first_move().source, bot.targetingArmy.tile)
                bot.info(f'continue killing target in exp plan, move {move}, plan was {str(expPath)}')
                return move
        else:
            bot.targetingArmy = None
            logbook.info(
                f"Stopped targetingArmy {str(bot.targetingArmy)} because it no longer exists in armyTracker.armies")

        if not bot.targetingArmy:
            return None

        enArmyDist = bot.distance_from_general(bot.targetingArmy.tile)
        armyStillInRange = enArmyDist < BotPathingUtils.distance_from_opp(bot, bot.targetingArmy.tile) + 2 or bot.territories.is_tile_in_friendly_territory(bot.targetingArmy.tile)
        if armyStillInRange and BotCombatOps.should_kill(bot, bot.targetingArmy.tile):
            forceKill = enArmyDist <= 4
            path = BotCombatOps.kill_army(bot, bot.targetingArmy, allowGeneral=True, allowWorthPathKillCheck=not forceKill)
            if path:
                move = BotPathingUtils.get_first_path_move(bot, path)
                if bot.targetingArmy is not None and bot.targetingArmy.tile.army / path.length < 1:
                    bot.info(f"Attacking army and ceasing to target army {str(bot.targetingArmy)}")
                    return move

                if not BotRepetition.detect_repetition(bot, move, 6, 3) and BotDefense.general_move_safe(bot, move.dest):
                    bot.info(
                        f"Cont kill army {str(bot.targetingArmy)} {'z' if move.move_half else ''}: {str(path)}")
                    bot.viewInfo.color_path(PathColorer(path, 0, 112, 133, 255, 10, 200))
                    return move
                else:
                    logbook.info(
                        f"Stopped targetingArmy {str(bot.targetingArmy)} because it was causing repetitions.")
                    bot.targetingArmy = None
        else:
            bot.viewInfo.add_info_line(
                f"Stopped targetingArmy {str(bot.targetingArmy)} due to armyStillInRange {armyStillInRange} or should_kill() returned false.")
            bot.targetingArmy = None

        return None

    @staticmethod
    def should_kill(bot, tile):
        if tile.isCity and abs(tile.delta.armyDelta) < 3:
            return False
        return True

    @staticmethod
    def just_moved(bot, tile):
        if abs(tile.delta.armyDelta) > 2:
            return True
        else:
            return False

    @staticmethod
    def should_kill_path_move_half(bot, threatKill, additionalArmy=0):
        start = threatKill.start.tile
        next = threatKill.start.next.tile
        threatKill.calculate_value(bot.general.player, teams=bot._map.team_ids_by_player_index)
        movingAwayFromEnemy = bot.board_analysis.intergeneral_analysis.bMap[start] < bot.board_analysis.intergeneral_analysis.bMap[next]
        move_half = movingAwayFromEnemy and threatKill.tail.tile.army + additionalArmy < (threatKill.value + threatKill.tail.tile.army) // 2

        if threatKill.tail.tile.isCity and threatKill.tail.tile.player >= 0:
            return False

        logbook.info(
            f"should_kill_path_move_half: movingAwayFromEnemy {movingAwayFromEnemy}\n                 threatKill.value = {threatKill.value}\n                 threatKill.tail.tile.army = {threatKill.tail.tile.army}\n                 (threatKill.value + threatKill.tail.tile.army) // 2 = {(threatKill.econValue + threatKill.tail.tile.army) // 2}\n                 : {move_half}")
        return move_half

    @staticmethod
    def find_key_enemy_vision_tiles(bot):
        keyTiles = set()
        genPlayer = bot._map.players[bot.general.player]
        distFactor = 2
        priorityDist = bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation) // distFactor
        if bot.targetPlayerExpectedGeneralLocation.isGeneral:
            distFactor = 3
            priorityDist = bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation) // distFactor + 1

        for tile in bot.general.adjacents:
            if bot._map.is_tile_enemy(tile):
                keyTiles.add(tile)
        for city in genPlayer.cities:
            if bot._map.turn - city.turn_captured > 20:
                for tile in city.adjacents:
                    if bot._map.is_tile_enemy(tile):
                        keyTiles.add(tile)

        for tile in bot._map.pathable_tiles:
            if bot._map.is_tile_enemy(tile):
                if bot.distance_from_general(tile) < priorityDist:
                    keyTiles.add(tile)

        cityAdjCount = 0
        for city, score in bot.cityAnalyzer.get_sorted_neutral_scores():
            if score.general_distances_ratio < 0.9:
                for adj in city.adjacents:
                    if bot._map.is_tile_enemy(adj):
                        cityAdjCount += 1
                        keyTiles.add(adj)

            if cityAdjCount > 5:
                break

        return keyTiles

    @staticmethod
    def worth_path_kill(bot, pathKill: Path, threatPath: Path, analysis=None, cutoffDistance=5):
        if pathKill.start is None or pathKill.tail is None:
            return False

        lenTillInThreatPath = 0
        node = pathKill.start
        while node is not None and node.tile not in threatPath.tileSet:
            lenTillInThreatPath += 1
            node = node.next

        shortEnoughPath = lenTillInThreatPath < max(3, threatPath.length - 1)
        logbook.info(
            f"worth_path_kill: shortEnoughPath = lenTillInThreatPath {lenTillInThreatPath} < max(3, threatPath.length - 1 ({threatPath.length - 1})): {shortEnoughPath}")
        if not shortEnoughPath:
            bot.viewInfo.paths.append(PathColorer(pathKill.clone(), 163, 129, 50, 255, 0, 100))
            logbook.info(f"  path kill eliminated due to shortEnoughPath {shortEnoughPath}")
            return False

        minSourceArmy = 8
        threatArmy = threatPath.start.tile.army
        if threatPath.start.tile in bot.armyTracker.armies:
            army = bot.armyTracker.armies[threatPath.start.tile]
            threatArmy = army.value
        threatMoved = abs(threatPath.start.tile.delta.armyDelta) >= 2
        if threatArmy < minSourceArmy and not threatMoved:
            logbook.info(
                f"  path kill eliminated due to not threatMoved and threatArmy {threatArmy} < minSourceArmy {minSourceArmy}")
            return False

        if not analysis:
            analysis = ArmyAnalyzer.build_from_path(bot._map, threatPath)
        lastTile = pathKill.tail.tile
        if pathKill.start.next.next is not None:
            lastTile = pathKill.start.next.next.tile
        startDist = bot.board_analysis.intergeneral_analysis.bMap[pathKill.start.tile]
        tailDist = bot.board_analysis.intergeneral_analysis.bMap[lastTile]
        movingTowardsOppo = startDist > tailDist
        canGoOtherDirection = True
        for node in bot.best_defense_leaves:
            if node.tile == pathKill.start.tile:
                canGoOtherDirection = False
        logbook.info(
            f"worth_path_kill: movingTowardsOppo {movingTowardsOppo}  ({pathKill.start.tile.toString()} [{startDist}]  ->  {lastTile.toString()} [{tailDist}])")
        onShortestPathwayAlready = (pathKill.start.tile in analysis.pathWayLookupMatrix[threatPath.start.tile].tiles
                                    or (pathKill.start.tile in analysis.pathWayLookupMatrix
                                        and analysis.pathWayLookupMatrix[pathKill.start.tile].distance < analysis.pathWayLookupMatrix[threatPath.start.tile].distance))

        logbook.info(
            f"worth_path_kill: onPath = pathKill.start.tile {pathKill.start.tile.toString()} in analysis.pathways[threatPath.start.tile {threatPath.start.tile.toString()}].tiles: {onShortestPathwayAlready}")

        enTilesInPath = SearchUtils.where(pathKill.tileList, lambda t: bot._map.is_tile_enemy(t))

        threatNegs = pathKill.tileSet.copy()
        threatNegs.add(threatPath.tail.tile)
        threatNegs.discard(threatPath.start.tile)
        killOverlap = pathKill.calculate_value(bot.general.player, teams=bot._map.team_ids_by_player_index, negativeTiles=threatPath.tileSet) - threatPath.calculate_value(threatPath.start.tile.player, teams=bot._map.team_ids_by_player_index, negativeTiles=threatNegs)

        turnsLeftInCycle = bot.timings.get_turns_left_in_cycle(bot._map.turn)
        turnsLeftInCycleCutoffThresh = turnsLeftInCycle // 2 - 1
        if pathKill.length - len(enTilesInPath) > turnsLeftInCycleCutoffThresh and canGoOtherDirection and not movingTowardsOppo:
            bot.viewInfo.add_info_line(f'Eliminated path kill due to len {pathKill.length} - enTilesInPath {len(enTilesInPath)} > cycleCutoffThresh {turnsLeftInCycleCutoffThresh}')
            return False

        logbook.info(f"  path kill worth it because not eliminated ({pathKill.toString()})")
        return True

    @staticmethod
    def kill_army(bot, army: Army, allowGeneral=False, allowWorthPathKillCheck=True):
        if len(army.expectedPaths) == 0:
            army.expectedPaths = ArmyTracker.get_army_expected_path(bot._map, army, bot.general, bot.armyTracker.player_targets)

        for path in army.expectedPaths:
            if path.start.tile != army.tile:
                continue
            if not path:
                logbook.info(f"In Kill_army: No bfs dynamic path found from army tile {str(army)} ???????")
                if bot.targetingArmy == army:
                    bot.targetingArmy = None
                return None

            killPath = BotCombatOps.kill_enemy_path(bot, path, allowGeneral)

            if killPath is not None:
                if not allowWorthPathKillCheck:
                    return killPath
                with bot.perf_timer.begin_move_event(f'build army analyzer for army kill of {repr(army)}'):
                    analyzer = ArmyAnalyzer(bot._map, bot.general, army.tile)
                worthPathKill = BotCombatOps.worth_path_kill(bot, killPath, path, analyzer)
                if worthPathKill:
                    return killPath

                bot.viewInfo.add_info_line(
                    f"NO army cont kill on {str(army)} because not worth with path {str(killPath)}")
                if bot.targetingArmy == army:
                    bot.targetingArmy = None
            else:
                bot.viewInfo.add_info_line(f"NO army cont kill on {str(army)}, no pathKill was found.")
                if bot.targetingArmy == army:
                    bot.targetingArmy = None

        return None

    @staticmethod
    def kill_enemy_path(bot, threatPath: Path, allowGeneral=False) -> Path | None:
        return BotCombatOps.kill_enemy_paths(bot, [threatPath], allowGeneral)

    @staticmethod
    def kill_enemy_paths(bot, threatPaths: typing.List[Path], allowGeneral=False) -> Path | None:
        threats = []

        allThreatsLow = True
        negativeTiles = set()

        with bot.perf_timer.begin_move_event('Kill Enemy Path ArmyAnalyzer'):
            for threatPath in threatPaths:
                armyAnalysis = ArmyAnalyzer.build_from_path(bot._map, threatPath)
                threat = ThreatObj(threatPath.length, threatPath.value, threatPath, ThreatType.Vision, armyAnalysis=armyAnalysis)
                threats.append(threat)
                threatPath.value = threatPath.calculate_value(bot.get_army_at(threatPath.start.tile).player, bot._map.team_ids_by_player_index, negativeTiles)

                if threatPath.value > 0:
                    allThreatsLow = False

        logbook.info(f"Starting kill_enemy_path for path {str(threatPath)}")

        if allThreatsLow:
            killPath = SearchUtils.dest_breadth_first_target(bot._map, [threatPath.start.tile], maxDepth=6, negativeTiles=negativeTiles, targetArmy=-1, additionalIncrement=-2)
            if killPath is not None:
                bot.info(f'kill_path dest low val @ {str(threatPath.start.tile)} KILL PATH {str(killPath)}')
                return killPath

        if not allowGeneral:
            negativeTiles.add(bot.general)

        for threat in threats:
            threatPath = threat.path
            shorterThreatPath = threatPath.get_subsegment(threatPath.length - 2)
            threatPathSet = shorterThreatPath.tileSet.copy()
            threatPathSet.discard(threatPath.start.tile)

            threatTile = threatPath.start.tile
            threatPlayer = threatPath.start.tile.player
            if threatTile in bot.armyTracker.armies:
                threatPlayer = bot.armyTracker.armies[threatTile].player
            threatPath.calculate_value(threatPlayer, teams=bot._map.team_ids_by_player_index)
            threatValue = max(threatPath.start.tile.army, threatPath.value)
            if threatTile.player != threatPlayer:
                threatValue = bot.armyTracker.armies[threatTile].value
            if threatValue <= 0:
                threatValue = threatTile.army
                if threatTile.player != threatPlayer:
                    threatValue = bot.armyTracker.armies[threatTile].value
                logbook.info(
                    f"threatValue was originally {threatPath.value}, removed player negatives and is now {threatValue}")
            else:
                logbook.info(f"threatValue is {threatValue}")

            if threat.turns > 0:
                directKillThresh = max(4, 2 * threatValue // threat.turns if threat.turns > 0 else 0)
                directKillThresh = min(threatValue, directKillThresh)
                for adj in threatPath.start.next.tile.movable:
                    if adj.player == bot.general.player and adj.army >= directKillThresh:
                        if adj.isGeneral and threat.armyAnalysis.chokeWidths[threatPath.start.next.tile] > 1:
                            bot.info(f"bypassed direct-kill gen move because choke width")
                            continue

                        path = Path()
                        path.add_next(adj)
                        path.add_next(threatPath.start.next.tile)
                        path.add_next(threatTile)
                        bot.info(f"returning nextTile direct-kill move {str(path)}")
                        return path

            directKillThresh = max(4, 3 * threatValue // threat.turns if threat.turns > 0 else 0)
            directKillThresh = min(threatValue, directKillThresh)

            for adj in threatTile.movable:
                if adj.player == bot.general.player and adj.army >= directKillThresh:
                    path = Path()
                    path.add_next(adj)
                    path.add_next(threatTile)
                    bot.info(f"returning direct-kill move {str(path)}")
                    return path

        threatCutoff = max(1, max(threats, key=lambda t: t.threatValue).threatValue - 10)

        killMove, gatherVal, gathTurns, gatherNodes = BotDefense.get_gather_to_threat_paths(bot, threats, gatherMax=True, addlTurns=-1, force_turns_up_threat_path=1, requiredContribution=threatCutoff, interceptArmy=True)

        if killMove is not None and gatherVal > threatCutoff:
            bot.info(f'kill_path gath @ {str(threatPath.start.tile)} {str(killMove)}')
            path = Path()
            path.add_next(killMove.source)
            path.add_next(killMove.dest)
            return path

    @staticmethod
    def kill_threat(bot, threat: ThreatObj, allowGeneral=False):
        return BotCombatOps.kill_enemy_path(bot, threat.path.get_subsegment(threat.path.length // 2), allowGeneral)

    @staticmethod
    def sum_enemy_army_near_tile(bot, startTile: Tile, distance: int = 2) -> int:
        enemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile) -> bool:
            if not (tile.isNeutral or bot._map.is_tile_friendly(tile)):
                enemyNear.add(tile.army - 1)
            return tile.isCity and tile.isNeutral and tile != startTile

        SearchUtils.breadth_first_foreach(bot._map, [startTile], distance, counterFunc, noLog=True, bypassDefaultSkip=True)
        value = enemyNear.value
        if bot._map.is_tile_enemy(startTile):
            value = value - (startTile.army - 1)
        return value

    @staticmethod
    def sum_player_army_near_tile(bot, tile: Tile, distance: int = 2, player: int | None = None) -> int:
        armyNear = BotCombatOps.sum_player_standing_army_near_or_on_tiles(bot, [tile], distance, player)
        logbook.info(f"player_army_near for tile {tile.x},{tile.y} player {player} returned {armyNear}")
        if tile.player == player:
            armyNear = armyNear - (tile.army - 1)
        return armyNear

    @staticmethod
    def sum_friendly_army_near_or_on_tiles(bot, tiles: typing.List[Tile], distance: int = 2, player: int | None = None) -> int:
        if player is None:
            player = bot._map.player_index
        armyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile):
            if bot._map.is_tile_on_team_with(tile, player):
                armyNear.add(tile.army - 1)

        SearchUtils.breadth_first_foreach(bot._map, tiles, distance, counterFunc)
        value = armyNear.value
        return value

    @staticmethod
    def find_end_of_turn_sim_result(bot, threat, kingKillPath: Path | None, time_limit: float | None = None) -> ArmySimResult | None:
        frArmies = BotCombatOps.get_largest_tiles_as_armies(bot, player=bot.general.player, limit=bot.behavior_end_of_turn_scrim_army_count)
        enArmies = BotCombatOps.get_largest_tiles_as_armies(bot, player=bot.targetPlayer, limit=bot.behavior_end_of_turn_scrim_army_count)

        if len(enArmies) == 0:
            bot.targetPlayerExpectedGeneralLocation.player = bot.targetPlayer
            enArmies = [bot.get_army_at(bot.targetPlayerExpectedGeneralLocation, no_expected_path=True)]

        enemyHasKillThreat = threat is not None and threat.threatType == ThreatType.Kill
        friendlyHasKillThreat = kingKillPath is not None

        if time_limit is None:
            time_limit = BotTimings.get_remaining_move_time(bot, )

        if time_limit < 0.06:
            logbook.info(f'not enough time left ({time_limit:.3f}) for end of turn scrim. Returning none.')
            return None

        old_allow_random_no_ops = bot.mcts_engine.allow_random_no_ops
        old_friendly_move_no_op_scale_10_fraction = bot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction
        old_enemy_move_no_op_scale_10_fraction = bot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction

        bot.mcts_engine.allow_random_no_ops = False
        bot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = 0
        bot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = 0

        simResult = BotCombatOps.get_armies_scrim_result(
            bot,
            frArmies,
            enArmies,
            enemyHasKillThreat=enemyHasKillThreat,
            friendlyHasKillThreat=friendlyHasKillThreat,
            time_limit=time_limit - 0.01)

        bot.mcts_engine.allow_random_no_ops = old_allow_random_no_ops
        bot.mcts_engine.eval_params.friendly_move_no_op_scale_10_fraction = old_friendly_move_no_op_scale_10_fraction
        bot.mcts_engine.eval_params.enemy_move_no_op_scale_10_fraction = old_enemy_move_no_op_scale_10_fraction

        bot.info(f'finScr {str(simResult)} {str(simResult.expected_best_moves)}')

        return simResult

    @staticmethod
    def find_end_of_turn_scrim_move(bot, threat, kingKillPath: Path | None, time_limit: float | None = None):
        simResult = BotCombatOps.find_end_of_turn_sim_result(bot, threat, kingKillPath, time_limit)

        if simResult is not None:
            friendlyPath, enemyPath = BotCombatOps.extract_engine_result_paths_and_render_sim_moves(bot, simResult)
            if friendlyPath is not None:
                return BotPathingUtils.get_first_path_move(bot, friendlyPath)

        return None

    @staticmethod
    def get_largest_tiles_as_armies(bot, player: int, limit: int) -> typing.List[Army]:
        player = bot._map.players[player]

        def sortFunc(t: Tile) -> float:
            pw = bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix[t]
            dist = 100
            if pw is not None:
                dist = pw.distance
            else:
                logbook.error(f'pathway none again for {str(t)}')
            return (t.army - 1) / (dist + 5)

        tiles = sorted(
            player.tiles,
            key=sortFunc,
            reverse=True)

        armies = [bot.get_army_at(t, no_expected_path=True) for t in tiles[0:limit] if t.army > 1]

        return armies

    @staticmethod
    def count_enemy_territory_near_tile(bot, startTile: Tile, distance: int = 2) -> int:
        enemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile) -> bool:
            tileIsNeutAndNotEnemyTerritory = tile.isNeutral and (tile.visible or bot.territories.territoryMap[tile] != bot.targetPlayer)
            if not tileIsNeutAndNotEnemyTerritory and bot._map.is_tile_enemy(tile):
                enemyNear.add(1)
            return tile.isObstacle and tile != startTile

        SearchUtils.breadth_first_foreach(bot._map, [startTile], distance, counterFunc, noLog=True, bypassDefaultSkip=True)
        value = enemyNear.value
        return value

    @staticmethod
    def count_enemy_tiles_near_tile(bot, startTile: Tile, distance: int = 2) -> int:
        enemyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile) -> bool:
            if not tile.isNeutral and not bot._map.is_tile_friendly(tile):
                enemyNear.add(1)

            return tile.isObstacle and tile != startTile

        SearchUtils.breadth_first_foreach(bot._map, [startTile], distance, counterFunc, noLog=True)
        value = enemyNear.value
        return value

    @staticmethod
    def sum_player_standing_army_near_or_on_tiles(bot, tiles: typing.List[Tile], distance: int = 2, player: int | None = None) -> int:
        if player is None:
            player = bot._map.player_index
        armyNear = SearchUtils.Counter(0)

        def counterFunc(tile: Tile):
            if tile.player != player:
                armyNear.add(tile.army - 1)

        SearchUtils.breadth_first_foreach_fast_no_neut_cities(bot._map, tiles, distance, counterFunc)
        value = armyNear.value
        return value

    @staticmethod
    def sum_friendly_army_near_tile(bot, tile: Tile, distance: int = 2, player: int | None = None) -> int:
        armyNear = BotCombatOps.sum_friendly_army_near_or_on_tiles(bot, [tile], distance, player)
        logbook.info(f"friendly_army_near for tile {tile.x},{tile.y} player {player} returned {armyNear}")
        if bot._map.is_tile_on_team_with(tile, player):
            armyNear = armyNear - (tile.army - 1)
        return armyNear

    @staticmethod
    def get_approximate_attack_defense_sweet_spot(
            bot,
            tile: Tile,
            negativeTiles,
            cycleBase: int = 10,
            cycleInterval: int = 5,
            minTurns: int = 0,
            maxTurns: int = 35,
            attackingPlayer: int = -1,
            defendingPlayer: int = -1,
            returnDiffThresh: int = 1000,
            noLog: bool = False
    ) -> typing.Tuple[int, int, int]:
        if attackingPlayer == -1:
            attackingPlayer = bot.general.player
        if defendingPlayer == -1:
            defendingPlayer = tile.player

        currentCycle = bot._map.turn % cycleBase
        left = cycleBase - currentCycle
        curLeft = left
        if curLeft < minTurns:
            curLeft += cycleInterval

        bestDiff = -1000
        curDiff = -1000
        theirDef = 0

        bestAttack = 0
        bestDef = 0
        bestTurns = curLeft

        while curLeft <= maxTurns and curDiff < returnDiffThresh:
            ourAttack = bot.win_condition_analyzer.get_approximate_attack_against(
                [tile],
                curLeft,
                attackingPlayer,
                0.005,
                forceFogRisk=False,
                negativeTiles=negativeTiles,
                noLog=True,
            )

            if ourAttack > 0:
                theirDef = bot.win_condition_analyzer.get_approximate_attack_against(
                    [tile],
                    curLeft,
                    defendingPlayer,
                    0.005,
                    forceFogRisk=False,
                    negativeTiles=None,
                    noLog=True,
                )

                curDiff = ourAttack - theirDef
                if not noLog:
                    logbook.info(f'atk/def @{tile}: diff {curDiff} (attack {ourAttack}, def {theirDef}')

            if curDiff <= bestDiff - 15 and ourAttack > 0 and bestAttack > 0:
                break

            if curDiff > bestDiff:
                bestAttack = ourAttack
                bestDef = theirDef
                bestTurns = curLeft
                bestDiff = curDiff

            curLeft += cycleInterval

        return bestTurns, bestAttack, bestDef

    @staticmethod
    def check_should_be_all_in_losing(bot) -> bool:
        general = bot.general
        if general is None:
            bot.is_all_in_losing = False
            return False

        if bot.targetPlayer == -1:
            bot.is_all_in_losing = False
            return False

        if not BotStateQueries.is_all_in(bot) and bot.force_far_gathers:
            return False

        customRatioOffset = 0.0
        if bot.is_weird_custom:
            customRatioOffset += 0.03
        if bot._map.is_walled_city_game:
            customRatioOffset += 0.07
        if bot._map.is_low_cost_city_game:
            customRatioOffset += 0.1
        customRatioMult = 1.0 + customRatioOffset

        frStats = bot._map.get_team_stats(bot.general.player)
        enStats = bot._map.get_team_stats(bot.targetPlayer)
        turnsLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)
        offset = 10
        if bot.is_weird_custom:
            offset = 25
        if bot._map.is_walled_city_game:
            offset += 30
        if bot._map.is_low_cost_city_game:
            offset += 40

        if bot.is_all_in_losing:
            offset = -6

        losingEnoughForCounter = enStats.tileCount + 35 * enStats.cityCount > frStats.tileCount * 1.05 * customRatioMult + (35 * frStats.cityCount) * customRatioMult + offset
        if bot.all_in_losing_counter == 0 and turnsLeft >= 30:
            offset = min(turnsLeft // 2, 13)
            losingEnoughForCounter = enStats.tileCount + 35 * enStats.cityCount > frStats.tileCount * 1.08 * customRatioMult + 35 * (frStats.cityCount + 1) * customRatioMult + offset

        if bot.is_all_in_losing:
            losingEnoughForCounter = enStats.tileCount + 35 * enStats.cityCount > frStats.tileCount * 1.01 * customRatioMult + (35 * frStats.cityCount) * customRatioMult + offset

        allInLosingCounterThreshold = frStats.tileCount // 5 + 15
        allInLosingCounterThreshold = max(50, allInLosingCounterThreshold)

        bot.is_all_in_losing = False

        if bot._map.remainingPlayers - len(BotTargeting.get_afk_players(bot)) <= 2 or bot._map.is_2v2:
            should2v2PartnerDeadAllIn = (bot._map.is_2v2 and bot.teammate_general is None and bot._map.remainingPlayers > 2)
            enJustContested = len(bot.cityAnalyzer.enemy_contested_cities)
            if should2v2PartnerDeadAllIn:
                bot.is_all_in_losing = True

            if bot._map.turn > 250 and enStats.tileCount + 20 * (enStats.cityCount - 1 - enJustContested) > frStats.tileCount * 1.3 * customRatioMult + 5 + 20 * (frStats.cityCount + 2) * customRatioMult and enStats.standingArmy > frStats.standingArmy * 1.25 * customRatioMult + 5:
                bot.is_all_in_losing = True
                bot.all_in_losing_counter = 200
            elif bot._map.turn > 150 and enStats.tileCount + 15 * enStats.cityCount > frStats.tileCount * 1.4 * customRatioMult + 5 + 15 * (frStats.cityCount + 2) * customRatioMult and enStats.standingArmy > frStats.standingArmy * 1.25 * customRatioMult + 5:
                bot.all_in_losing_counter += 3
            elif should2v2PartnerDeadAllIn or (not bot.is_all_in_army_advantage and bot._map.turn > 50 and losingEnoughForCounter):
                bot.all_in_losing_counter += 1
            else:
                bot.all_in_losing_counter = 0
            if bot.all_in_losing_counter > allInLosingCounterThreshold:
                bot.is_all_in_losing = True
            if enStats.tileCount + 35 * enStats.cityCount > frStats.tileCount * 1.5 * customRatioMult + 5 + 35 * frStats.cityCount and enStats.score > frStats.score * 1.6 * customRatioMult + 5:
                bot.giving_up_counter += 1
                logbook.info(
                    f"It looks like we're getting wrecked. givingUpCounter {bot.giving_up_counter}")
                BotComms.send_all_chat_communication(bot, "gg")
                time.sleep(1)
                if bot.surrender_func:
                    bot.surrender_func()
                time.sleep(1)
                bot._map.result = False
                bot._map.complete = True
            else:
                bot.giving_up_counter = 0

        if bot.is_all_in_losing:
            bot.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0)
            bot.city_expand_plan = None
            bot.enemy_expansion_plan = None

        bot._minAllowableArmy = 1
        return bot.is_all_in_losing

    @staticmethod
    def worth_attacking_target(bot) -> bool:
        timingFactor = 1.0
        if bot._map.turn < 50:
            bot.viewInfo.add_info_line("Not worth attacking, turn < 50")
            return False

        knowsWhereEnemyGeneralIs = bot.targetPlayer != -1 and bot._map.generals[bot.targetPlayer] is not None

        if bot.targetPlayer == -1:
            shouldAttack = bot._map.remainingPlayers == 2
            bot.viewInfo.add_info_line(f"FFA no tiles path worth attacking: {shouldAttack}")
            return shouldAttack

        frStats = bot._map.get_team_stats(bot.general.player)
        enStats = bot._map.get_team_stats(bot.targetPlayer)

        wPStanding = frStats.standingArmy * 0.9
        oppStanding = enStats.standingArmy
        wPIncome = frStats.tileCount + frStats.cityCount * 30
        wOppIncome = enStats.tileCount * 1.2 + enStats.cityCount * 35 + 5
        if bot._map.turn >= 100 and wPStanding < oppStanding and wPIncome > wOppIncome:
            bot.viewInfo.add_info_line("NOT WORTH ATTACKING TARGET BECAUSE wPStanding < oppStanding and wPIncome > wOppIncome")
            bot.viewInfo.add_info_line(
                f"NOT WORTH ATTACKING TARGET BECAUSE {wPStanding}     <  {oppStanding}        and   {wPIncome} >   {wOppIncome}")
            return False

        if bot.target_player_gather_path is None:
            logbook.info("ELIM due to no path")
            return False
        value = BotStateQueries.get_player_army_amount_on_path(bot, bot.target_player_gather_path, bot._map.player_index, 0, bot.target_player_gather_path.length)
        logbook.info(
            f"Player army amount on path: {value}   TARGET PLAYER PATH IS REVERSED ? {bot.target_player_gather_path.toString()}")
        subsegment = bot.get_value_per_turn_subsegment(bot.target_player_gather_path)
        logbook.info(f"value per turn subsegment = {subsegment.toString()}")
        subsegmentTargets = subsegment.tileSet

        lengthRatio = len(bot.target_player_gather_targets) / max(1, len(subsegmentTargets))

        sqrtVal = 0
        if value > 0:
            sqrtVal = value ** 0.5
            logbook.info(f"value ** 0.5 -> sqrtVal {sqrtVal}")
        if frStats.tileCount < 60:
            sqrtVal = value / 2.0
            logbook.info(f"value / 2.3  -> sqrtVal {sqrtVal}")
        sqrtVal = min(20, sqrtVal)

        dist = int((len(subsegmentTargets)) + sqrtVal)
        factorTurns = 50
        if dist > 25 or frStats.tileCount > 110:
            factorTurns = 100
        turnOffset = bot._map.turn + dist
        factorScale = turnOffset % factorTurns
        if factorScale < factorTurns / 2:
            logbook.info("factorScale < factorTurns / 2")
            timingFactor = scale(factorScale, 0, factorTurns / 2, 0, 0.40)
        else:
            logbook.info("factorScale >>>>>>>>> factorTurns / 2")
            timingFactor = scale(factorScale, factorTurns / 2, factorTurns, 0.30, 0)

        if bot.lastTimingFactor != -1 and bot.lastTimingFactor < timingFactor:
            logbook.info(
                f"  ~~~  ---  ~~~  lastTimingFactor {'%.3f' % bot.lastTimingFactor} <<<< timingFactor {'%.3f' % timingFactor}")
            factor = bot.lastTimingFactor
            bot.lastTimingFactor = timingFactor
            timingFactor = factor
        bot.lastTimingTurn = bot._map.turn

        if frStats.tileCount > 200:
            timingFactor = 0.1

        alreadyAttacking = False
        if bot._map.turn - 3 < bot.lastTargetAttackTurn:
            timingFactor *= 0.3
            alreadyAttacking = True
            logbook.info("already attacking :)")

        if frStats.standingArmy < 5 and timingFactor > 0.1:
            return False
        logbook.info(
            f"OoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoOoO\n   {bot._map.turn}  oOo  timingFactor {'%.3f' % timingFactor},  factorTurns {factorTurns},  turnOffset {turnOffset},  factorScale {factorScale},  sqrtVal {'%.1f' % sqrtVal},  dist {dist}")

        playerEffectiveStandingArmy = frStats.standingArmy - 9 * (frStats.cityCount - 1)
        if bot.target_player_gather_path.length < 2:
            logbook.info(
                f"ELIM due to path length {bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation)}")
            return False

        targetPlayerArmyThreshold = bot._map.players[bot.targetPlayer].standingArmy + dist / 2
        if frStats.standingArmy < 70:
            timingFactor *= 2
            timingFactor = timingFactor ** 2
            if knowsWhereEnemyGeneralIs:
                timingFactor += 0.05
            rawNeeded = playerEffectiveStandingArmy * 0.62 + playerEffectiveStandingArmy * timingFactor
            rawNeededScaled = rawNeeded * lengthRatio
            neededVal = min(targetPlayerArmyThreshold, rawNeededScaled)
            if alreadyAttacking:
                neededVal *= 0.75
            logbook.info(
                f"    --   playerEffectiveStandingArmy: {playerEffectiveStandingArmy},  NEEDEDVAL: {'%.1f' % neededVal},            VALUE: {value}")
            logbook.info(
                f"    --                                     rawNeeded: {'%.1f' % rawNeeded},  rawNeededScaled: {'%.1f' % rawNeededScaled},  lengthRatio: {'%.1f' % lengthRatio}, targetPlayerArmyThreshold: {'%.1f' % targetPlayerArmyThreshold}")
            return value > neededVal
        else:
            if knowsWhereEnemyGeneralIs:
                timingFactor *= 1.5
                timingFactor += 0.03
            expBase = playerEffectiveStandingArmy * 0.15
            exp = 0.68 + timingFactor
            expValue = playerEffectiveStandingArmy ** exp
            rawNeeded = expBase + expValue
            rawNeededScaled = rawNeeded * lengthRatio
            neededVal = min(targetPlayerArmyThreshold, rawNeededScaled)
            if alreadyAttacking:
                neededVal *= 0.75
            logbook.info(
                f"    --    playerEffectiveStandingArmy: {playerEffectiveStandingArmy},  NEEDEDVAL: {'%.1f' % neededVal},            VALUE: {value},      expBase: {'%.2f' % expBase},   exp: {'%.2f' % exp},       expValue: {'%.2f' % expValue}")
            logbook.info(
                f"    --                                      rawNeeded: {'%.1f' % rawNeeded},  rawNeededScaled: {'%.1f' % rawNeededScaled},  lengthRatio: {'%.1f' % lengthRatio}, targetPlayerArmyThreshold: {'%.1f' % targetPlayerArmyThreshold}")
            return value >= neededVal

    @staticmethod
    def determine_should_winning_all_in(bot):
        if bot.targetPlayer < 0:
            return False

        targetPlayer = bot._map.players[bot.targetPlayer]
        if len(targetPlayer.tiles) == 0:
            return False
        thisPlayer = bot._map.players[bot.general.player]

        ourArmy = thisPlayer.standingArmy
        oppArmy = targetPlayer.standingArmy

        for player in bot._map.players:
            if player.index == bot.targetPlayer or player.index == bot.general.player:
                continue

            if bot._map.is_player_on_team_with(bot.targetPlayer, player.index):
                oppArmy += player.standingArmy
            elif bot._map.is_player_on_team_with(bot.general.player, player.index):
                ourArmy += player.standingArmy

        if ourArmy < 100:
            return False

        factoredArmyThreshold = oppArmy * 2 + bot.shortest_path_to_target_player.length

        if bot.is_all_in_army_advantage:
            factoredArmyThreshold = oppArmy * 1.4 + bot.shortest_path_to_target_player.length // 2

        if ourArmy > factoredArmyThreshold:
            bot.viewInfo.add_info_line(f"TEMP ALL IN ON ARMY ADV {ourArmy} vs {oppArmy} thresh({factoredArmyThreshold:.2f})")
            return True

        return False

    @staticmethod
    def check_for_army_movement_scrims(bot, econCutoff=2.0) -> Move | None:
        curScrim = 0
        cutoff = 3

        bestScrimPath: Path | None = None
        bestScrim: ArmySimResult | None = None

        cutoffDist = bot.board_analysis.inter_general_distance // 2

        for tile in sorted(bot.armies_moved_this_turn, key=lambda t: t.army, reverse=True):
            if tile.player == bot.targetPlayer:
                if tile.army <= 4:
                    continue

                if bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, tile) > cutoffDist:
                    continue

                if (
                        bot.next_scrimming_army_tile is not None
                        and bot.next_scrimming_army_tile.army > 2
                        and bot.next_scrimming_army_tile.player == bot.general.player
                        and bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, bot.next_scrimming_army_tile) <= cutoffDist
                ):
                    with bot.perf_timer.begin_move_event(
                            f'Scrim prev {str(bot.next_scrimming_army_tile)} @ {str(tile)}'):
                        friendlyPath, enemyPath, simResult = BotCombatOps.get_army_scrim_paths(
                            bot,
                            bot.next_scrimming_army_tile,
                            enemyArmyTile=tile,
                            enemyCannotMoveAway=True)
                    if simResult is not None \
                            and (bestScrimPath is None or bestScrim.best_result_state.calculate_value_int() < simResult.best_result_state.calculate_value_int()):
                        bot.info(f'new best scrim @ {str(tile)} {simResult.net_economy_differential:+0.1f} ({str(simResult)}) {str(friendlyPath)}')
                        bestScrimPath = friendlyPath
                        bestScrim = simResult
                else:
                    bot.next_scrimming_army_tile = None

                curScrim += 1
                army = BotStateQueries.get_army_at(bot, tile)
                with bot.perf_timer.begin_move_event(f'try scrim @{army.name} {str(tile)}'):
                    if len(army.expectedPaths) == 0:
                        targets = bot._map.players[bot.general.player].cities.copy()
                        targets.append(bot.general)
                        if bot.teammate_general is not None:
                            targets.append(bot.teammate_general)
                            targets.extend(bot._map.players[bot.teammate].cities)
                        targetPath = BotPathingUtils.get_path_to_targets(
                            bot,
                            targets,
                            0.1,
                            preferNeutral=False,
                            fromTile=tile)
                        if targetPath:
                            army.include_path(targetPath)
                        bot.viewInfo.add_info_line(f'predict army {army.name} path {str(army.expectedPaths)}')

                    path, scrimResult = BotCombatOps.try_find_counter_army_scrim_path(bot, army.expectedPaths[0], allowGeneral=True)
                    if path is not None and scrimResult is not None:
                        if scrimResult.best_result_state.captured_by_enemy:
                            bot.viewInfo.add_info_line(f'scrim says cap by enemy in {str(scrimResult.best_result_state)} @{army.name} {str(tile)} lol')
                        elif (bestScrimPath is None
                              or bestScrim.best_result_state.calculate_value_int() < scrimResult.best_result_state.calculate_value_int()):
                            if scrimResult.net_economy_differential < 0:
                                bot.viewInfo.add_info_line(f'scrim @ {str(tile)} bad result, {str(scrimResult)} including anyway as new best scrim')
                            else:
                                bot.info(
                                    f'new best scrim @ {str(tile)} {scrimResult.net_economy_differential:+.1f} ({str(scrimResult)}) {str(path)}')
                            bestScrimPath = path
                            bestScrim = scrimResult

                if curScrim > cutoff:
                    break

        if bestScrimPath is not None and bestScrim is not None and bestScrim.net_economy_differential > econCutoff:
            bot.info(f'Scrim cont ({str(bestScrim)}) {str(bestScrimPath)}')

            bot.next_scrimming_army_tile = bestScrimPath.start.next.tile
            return BotPathingUtils.get_first_path_move(bot, bestScrimPath)

        return None

    @staticmethod
    def get_scrim_cached(bot, friendlyArmies: typing.List[Army], enemyArmies: typing.List[Army]) -> ArmySimResult | None:
        key = BotCombatOps.get_scrim_cache_key(bot, friendlyArmies, enemyArmies)
        cachedSimResult: ArmySimResult | None = bot.cached_scrims.get(key, None)
        return cachedSimResult

    @staticmethod
    def get_scrim_cache_key(bot, friendlyArmies: typing.List[Army], enemyArmies: typing.List[Army]) -> str:
        sortedArmies = list(sorted(friendlyArmies, key=lambda a: a.tile))
        sortedArmies.extend(list(sorted(enemyArmies, key=lambda a: a.tile)))
        key = ''.join([str(a.tile) for a in sortedArmies])
        return key

    @staticmethod
    def check_for_attack_launch_move(bot, outLaunchPlanNegatives: typing.Set[Tile]) -> Move | None:
        if bot.target_player_gather_path is None and not bot.flanking:
            return None

        cycleTurn = bot.timings.get_turn_in_cycle(bot._map.turn)
        cycleTurnsLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)

        if not bot._map.is_low_cost_city_game and not BotTargeting.is_ffa_situation(bot) and bot.player.tileCount < 45:
            if len([t for t in bot.player.tiles if t.army > 1 and t not in bot.target_player_gather_targets]) > 0:
                bot.info(f'Skipping launch because unused tiles')
                return None

        from BotModules.BotPathingUtils import BotPathingUtils
        path = BotPathingUtils.get_value_per_turn_subsegment(bot, bot.target_player_gather_path, 1.0, 0.25)
        origPathLength = path.length

        targetPathLength = path.length * 3 // 9 + 1

        if bot.flanking:
            targetPathLength = targetPathLength // 2 + 1

        maxLength = 17
        if bot.timings.cycleTurns > 50:
            maxLength = 34

        targetPathLength = min(maxLength, targetPathLength)
        path = path.get_subsegment(targetPathLength)
        if path.length == 0:
            return None

        path.calculate_value(bot.general.player, teams=bot._map.team_ids_by_player_index)
        logbook.info(f"  value subsegment = {str(path)}")
        timingTurn = (bot._map.turn + bot.timings.offsetTurns) % bot.timings.cycleTurns
        player = bot._map.players[bot.general.player]

        enemyGenAdj = []
        for generalAdj in bot.general.adjacents:
            if bot._map.is_tile_enemy(generalAdj):
                bot.viewInfo.add_targeted_tile(generalAdj)
                enemyGenAdj.append(generalAdj)

        pathWorth = BotStateQueries.get_player_army_amount_on_path(bot, bot.target_player_gather_path, bot.general.player)

        if bot._map.turn >= 50 and bot.timings.in_launch_timing(bot._map.turn) and (
                bot.targetPlayer != -1 or bot._map.remainingPlayers <= 2):
            inAttackWindow = timingTurn < bot.timings.launchTiming + 4
            minArmy = min(player.standingArmy ** 0.9, (player.standingArmy ** 0.72) * 1.7)
            if bot.flanking and pathWorth > 0:
                minArmy = 0

            bot.info(
                f"  T Launch window {inAttackWindow} - minArmy {minArmy}, pathVal {path.value}, timingTurn {timingTurn} < launchTiming + origPathLength {origPathLength} / 3 {bot.timings.launchTiming + origPathLength / 2:.1f}")

            if path is not None and path.length > 0 and pathWorth > minArmy and inAttackWindow and path.start.tile.player == bot.general.player:
                move = BotPathingUtils.get_first_path_move(bot, path)
                if BotDefense.is_move_safe_against_threats(bot, move):
                    logbook.info(
                        f"  attacking because NEW worth_attacking_target(), pathWorth {pathWorth}, minArmy {minArmy}: {str(path)}")
                    bot.lastTargetAttackTurn = bot._map.turn
                    if bot.timings.is_early_flank_launch:
                        path.start.move_half = True
                    bot.curPath = path
                    return move

            elif path is not None:
                logbook.info(
                    "  Did NOT attack because NOT pathWorth > minArmy or not inAttackWindow??? pathWorth {}, minArmy {}, inAttackWindow {}: {}".format(
                        pathWorth, minArmy, path.toString(), inAttackWindow))
            else:
                logbook.info("  Did not attack because path was None.")
        else:
            logbook.info("skipped launch because outside launch window")

        return None

    @staticmethod
    def try_find_army_out_of_position_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        thresh = bot.targetPlayerObj.standingArmy ** 0.6
        logbook.info(f'Checking for out of position tiles with army greater than threshold {thresh:.0f}')
        outOfPositionArmies = []
        for tile in bot.largePlayerTiles:
            distFr = bot.board_analysis.intergeneral_analysis.aMap[tile]
            distEn = bot.board_analysis.intergeneral_analysis.bMap[tile]

            if tile in bot.board_analysis.extended_play_area_matrix and distEn > distFr:
                continue

            if tile in bot.board_analysis.core_play_area_matrix and distEn * 2 > distFr:
                continue

            if tile.army < thresh:
                continue

            if bot.territories.is_tile_in_friendly_territory(tile):
                continue

            outOfPositionArmies.append(bot.get_army_at(tile))

            if len(outOfPositionArmies) > 5:
                break

        if len(outOfPositionArmies) == 0:
            return None

        result = BotCombatOps.get_armies_scrim_result(bot, friendlyArmies=outOfPositionArmies, enemyArmies=BotCombatOps.get_largest_tiles_as_armies(bot, bot.targetPlayer, 7), enemyCannotMoveAway=False)

        if result is not None:
            friendlyPath, enemyPath = BotCombatOps.extract_engine_result_paths_and_render_sim_moves(bot, result)
            if friendlyPath is not None:
                move = BotPathingUtils.get_first_path_move(bot, friendlyPath)
                bot.info(f'Army out of position scrim {move}')
                return move

        return None

    @staticmethod
    def try_find_flank_all_in(bot, hitGeneralAtTurn: int) -> Move | None:
        launchPoint: Move | None = None
        return None

    @staticmethod
    def try_get_cyclic_all_in_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        winningEc = bot.opponent_tracker.winning_on_economy(byRatio=1.15)
        winningTile = bot.opponent_tracker.winning_on_tiles(byRatio=1.1)
        winningArmy = bot.opponent_tracker.winning_on_army(byRatio=1.45)
        staySafe = True
        if BotTargeting.is_ffa_situation(bot) and not BotTimings.is_player_aggressive(bot, bot.targetPlayer, turnPeriod=75):
            staySafe = False

        reason = ''
        if bot.is_all_in_losing:
            reason = 'lose '
            staySafe = False

        if bot.is_winning_gather_cyclic or (winningEc and winningTile and winningArmy and bot.targetPlayer != -1) or bot.is_all_in_losing:
            remainingTurns = max(5, bot.timings.get_turns_left_in_cycle(bot._map.turn) - 5)
            negatives = defenseCriticalTileSet.copy()
            negatives.update(bot.cities_gathered_this_cycle)

            if not bot.is_all_in_losing:
                reason = 'win '
                cycleTurns = bot.timings.get_turns_left_in_cycle(bot._map.turn)
                if cycleTurns > 30:
                    bot.is_winning_gather_cyclic = True
                negatives.update(cd.tile for cd in BotTargeting.get_contested_targets(bot, shortTermContestCutoff=50, longTermContestCutoff=100, numToInclude=5, excludeGeneral=True))

                for city in bot.player.cities:
                    if not bot.territories.is_tile_in_friendly_territory(city):
                        negatives.add(city)

            enAttackPath: Path | None = None
            if remainingTurns > 0:
                targets = BotTargeting.get_target_player_possible_general_location_tiles_sorted(bot, elimNearbyRange=4)[0:4]
                for target in targets:
                    bot.viewInfo.add_targeted_tile(target, TargetStyle.RED)

                if not bot.is_all_in_losing:
                    for city in bot.targetPlayerObj.cities:
                        bot.viewInfo.add_targeted_tile(city, TargetStyle.ORANGE)

                    targets.extend(bot.targetPlayerObj.cities)
                    enAttackPath = bot.enemy_attack_path
                    if enAttackPath is not None:
                        enTiles = []
                        for tile in enAttackPath.tileList:
                            if bot._map.is_tile_enemy(tile) or not tile.visible:
                                enTiles.append(tile)

                        if len(enTiles) > 5 and len(enTiles) > bot.shortest_path_to_target_player.length // 2:
                            reason = f'{reason}EnAttk '
                            for t in enTiles:
                                if bot.distance_from_general(t) < bot.shortest_path_to_target_player.length // 2:
                                    targets.append(t)
                            remainingTurns = remainingTurns % 25
                        else:
                            enAttackPath = None

                with bot.perf_timer.begin_move_event(f'{reason}gather cyclic {remainingTurns}'):
                    move_closest_value_func = None
                    if enAttackPath is not None:
                        analysis = ArmyAnalyzer.build_from_path(bot._map, enAttackPath)
                        fakeThreat = ThreatObj(enAttackPath.length, 1, enAttackPath, ThreatType.Vision, armyAnalysis=analysis)
                        move_closest_value_func = BotDefense.get_defense_tree_move_prio_func(bot, fakeThreat)

                    gcp = Gather.gather_approximate_turns_to_tiles(
                        bot._map,
                        targets,
                        remainingTurns,
                        bot.player.index,
                        gatherMatrix=BotGatherOps.get_gather_tiebreak_matrix(bot, ),
                        negativeTiles=negatives,
                        prioritizeCaptureHighArmyTiles=not bot.is_all_in_losing,
                        useTrueValueGathered=True,
                        includeGatherPriorityAsEconValues=False,
                        timeLimit=min(0.05, BotTimings.get_remaining_move_time(bot, ))
                    )

                    if gcp is not None:
                        if move_closest_value_func is not None:
                            gcp.value_func = move_closest_value_func
                        move = gcp.get_first_move()
                        bot.gatherNodes = gcp.root_nodes
                        bot.info(f'pcst {reason}gath cyc {remainingTurns} {move} @ {BotStateQueries.str_tiles(bot, targets)} neg {BotStateQueries.str_tiles(bot, negatives)}')
                        return move

        return None
