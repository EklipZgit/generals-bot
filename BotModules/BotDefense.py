import time
import typing

import logbook

import Gather
import SearchUtils
from Algorithms import MapSpanningUtils
from BotModules.BotStateQueries import BotStateQueries
from Behavior.ArmyInterceptor import InterceptionOptionInfo
from DangerAnalyzer import ThreatType
from Gather import GatherTreeNode
from DangerAnalyzer import ThreatObj
from Interfaces import TilePlanInterface, MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet, TileSet
from Behavior.ArmyInterceptor import ThreatBlockInfo
import DebugHelper
from Path import Path
from base import Colors
from ViewInfo import TargetStyle, PathColorer
from Models.Move import Move
from base.client.map import Tile, MapBase


class BotDefense:
    @staticmethod
    def determine_fog_defense_amount_available_for_tiles(bot, targetTiles, enPlayer, fogDefenseTurns: int = 0, fogReachTurns: int = 8) -> int:
        """Does NOT include the army that is on the targetTiles."""
        targetArmy = bot.opponent_tracker.get_approximate_fog_army_risk(enPlayer, cityLimit=None, inTurns=fogDefenseTurns)

        genReachable = SearchUtils.build_distance_map_matrix_with_skip(bot._map, targetTiles, skipTiles=bot._map.visible_tiles)

        used = set()
        for army in bot.armyTracker.armies.values():
            if army.player != enPlayer:
                continue

            if army.name in used:
                continue

            if army.tile.visible:
                continue

            anyReachable = False
            if genReachable.raw[army.tile.tile_index] is None or genReachable.raw[army.tile.tile_index] >= fogReachTurns:
                for entangled in army.entangledArmies:
                    if genReachable.raw[entangled.tile.tile_index] is not None and genReachable.raw[entangled.tile.tile_index] < fogReachTurns:
                        anyReachable = True
            else:
                anyReachable = True

            if not anyReachable:
                targetArmy -= army.value

                used.add(army.name)

        return targetArmy

    @staticmethod
    def get_defense_moves(
            bot,
            defenseCriticalTileSet: typing.Set[Tile],
            raceEnemyKingKillPath: Path | None,
            raceChance: float
    ) -> typing.Tuple[Move | None, Path | None]:
        move: Move | None = None

        outputDefenseCriticalTileSet = defenseCriticalTileSet
        bot.best_defense_leaves: typing.List[GatherTreeNode] = []

        threats = []
        if bot.dangerAnalyzer.fastestThreat is not None and bot.dangerAnalyzer.fastestThreat.turns > -1:
            threats.append(bot.dangerAnalyzer.fastestThreat)
        if bot.dangerAnalyzer.fastestAllyThreat is not None and bot.dangerAnalyzer.fastestAllyThreat.turns > -1:
            if len(threats) > 0 and threats[0].path.start.tile == bot.dangerAnalyzer.fastestAllyThreat.path.start.tile and threats[0].turns - 1 > bot.dangerAnalyzer.fastestAllyThreat.turns:
                bot.info(f'IGNORING SELF THREAT DUE TO ALLY BEING CLOSER TO DEATH ({threats[0].turns} vs {bot.dangerAnalyzer.fastestAllyThreat.turns})')
                threats = []
            threats.append(bot.dangerAnalyzer.fastestAllyThreat)
        if bot.dangerAnalyzer.fastestCityThreat is not None and bot.dangerAnalyzer.fastestCityThreat.turns > -1:
            threats.append(bot.dangerAnalyzer.fastestCityThreat)

        negativeTilesIncludingThreat = outputDefenseCriticalTileSet.copy()

        for threat in threats:
            if threat is not None and threat.threatType == ThreatType.Kill:
                for tile in threat.path.tileSet:
                    negativeTilesIncludingThreat.add(tile)

        movesToMakeAnyway = []

        realThreats = []
        anyRealThreat = False
        for threat in threats:
            interceptMove, interceptPath, intOption, interceptDelayed = bot.check_defense_intercept_move(threat)
            if interceptDelayed:
                bot.viewInfo.add_info_line(f'DEFENSE INTERCEPT SAID DELAYED AGAINST THREAT, NO OPPING DEFENSE')
                negativeTilesIncludingThreat.update(interceptPath.tileList)
                outputDefenseCriticalTileSet.update(interceptPath.tileList)
                continue

            if interceptMove is not None and intOption is not None and intOption.econValue / intOption.length > 2.5:
                vt = intOption.econValue / intOption.length
                bot.info(f'def int move against {threat.path.start.tile} vt {vt:.2f} ({intOption.econValue:.2f}/{intOption.length}), blk {intOption.damage_blocked:.1f}, wci {intOption.worst_case_intercept_moves}, bci {intOption.best_case_intercept_moves}, rt {intOption.recapture_turns}')
                return interceptMove, interceptPath

            isRealThreat = True
            isEconThreat = not threat.path.tail.tile.isGeneral

            army = bot.armyTracker.armies.get(threat.path.start.tile, None)
            if army and army.visible and army.last_moved_turn > bot._map.turn - 2:
                logbook.info(f'get_defense_moves setting targetingArmy to real threat army {str(army)}')
                bot.targetingArmy = army

            threatMovingWrongWay = False
            threatTile = threat.path.start.tile
            if threatTile.delta.fromTile:
                threatDist = threat.armyAnalysis.aMap[threatTile]
                threatFromDist = threat.armyAnalysis.aMap[threatTile.delta.fromTile]
                if threatDist >= threatFromDist:
                    threatMovingWrongWay = True

            savePath: Path | None = None
            searchTurns = threat.turns

            armyAmount = threat.threatValue + 1
            logbook.info(
                f"\n!-!-!-!-!-! danger in {threat.turns}, gather {armyAmount} in {searchTurns} turns  !-!-!-!-!-!")

            bot.viewInfo.add_targeted_tile(threat.path.tail.tile)
            flags = ''
            if threat is not None and threat.threatType == ThreatType.Kill:
                survivalThreshold = threat.threatValue
                distOffsetNOWUNUSED = 1
                addlTurnsToAllowGatherForAlwaysZero = 0
                saveTurns = threat.turns
                if threat is not None and bot._map.player_has_priority_over_other(bot.player.index, threat.threatPlayer, bot._map.turn + threat.turns) and not bot.has_defenseless_modifier:
                    distOffsetNOWUNUSED += 1
                if threat.saveTile is not None or isEconThreat and addlTurnsToAllowGatherForAlwaysZero == 0:
                    saveTurns += 1

                if threat.turns > 2 * bot.shortest_path_to_target_player.length // 3:
                    distOffsetNOWUNUSED = 0
                shouldBypass = bot.should_bypass_army_danger_due_to_last_move_turn(threat.path.start.tile)
                if shouldBypass:
                    bot.viewInfo.add_info_line(f'skip def dngr from{str(army.tile)} last_seen {army.last_seen_turn}, last_moved {army.last_moved_turn}')
                    distOffsetNOWUNUSED -= 1

                with bot.perf_timer.begin_move_event(f'Def Gath {saveTurns}t @ {str(threat.path.start.tile)}->{str(threat.path.tail.tile)}'):
                    additionalNegatives = set()
                    if bot.teammate_communicator is not None:
                        survivalThreshold, additionalNegatives = bot.teammate_communicator.get_additional_defense_negatives_and_contribution_requirement(threat)
                    bot.viewInfo.add_stats_line('WHITE O: teammate defense negativess')
                    for tile in additionalNegatives:
                        bot.viewInfo.add_targeted_tile(tile, TargetStyle.WHITE, radiusReduction=9)
                    outputDefenseCriticalTileSet.update(additionalNegatives)
                    timeLimit = 0.05
                    if not threat.path.tail.tile.isGeneral:
                        timeLimit = 0.015
                    move, valueGathered, turnsUsed, gatherNodes = bot.get_gather_to_threat_path(
                        threat,
                        requiredContribution=survivalThreshold,
                        additionalNegatives=additionalNegatives,
                        addlTurns=addlTurnsToAllowGatherForAlwaysZero,
                        timeLimit=timeLimit)

                    if gatherNodes is not None:
                        leavesGreaterThanDistance = GatherTreeNode.get_tree_leaves_further_than_distance(gatherNodes, threat.armyAnalysis.aMap, threat.turns, survivalThreshold)
                        anyLeafIsSameDistAsThreat = len(leavesGreaterThanDistance) > 0
                        if anyLeafIsSameDistAsThreat:
                            bot.info(f'defense anyLeafIsSameDistAsThreat {anyLeafIsSameDistAsThreat}')
                        move_closest_value_func = bot.get_defense_tree_move_prio_func(threat, anyLeafIsSameDistAsThreat, printDebug=DebugHelper.IS_DEBUGGING)
                        move = bot.get_tree_move_default(gatherNodes, move_closest_value_func)
                if move:
                    with bot.perf_timer.begin_move_event(f'Def prun @ {str(threat.path.start.tile)}->{str(threat.path.tail.tile)}'):
                        if valueGathered > survivalThreshold:
                            pruned = GatherTreeNode.clone_nodes(gatherNodes)
                            sumPrunedTurns, sumPruned, pruned = Gather.prune_mst_to_army_with_values(
                                pruned,
                                survivalThreshold + 1,
                                bot.general.player,
                                MapBase.get_teams_array(bot._map),
                                bot._map.turn,
                                viewInfo=bot.viewInfo,
                                preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                                noLog=False)

                            if (bot.is_blocking_neutral_city_captures or valueGathered - sumPruned < 45) and not isEconThreat:
                                bot.block_neutral_captures('due to pruned defense being less than safe if we take the city.')

                            citiesInPruned = SearchUtils.Counter(0)
                            GatherTreeNode.foreach_tree_node(pruned, lambda n: citiesInPruned.add(1 * ((n.tile.isGeneral or n.tile.isCity) and bot._map.is_tile_friendly(n.tile))))
                            turnGap = threat.turns - sumPrunedTurns
                            sumPruned += (turnGap * citiesInPruned.value // 2)
                            if sumPruned < survivalThreshold:
                                if SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING:
                                    raise AssertionError(
                                        f'We should absolutely never get here with army pruned {sumPruned} being less than threat {survivalThreshold} but inside the original gather {valueGathered} greater than threat.')

                            flipThingy = 0
                            leavesGreaterThanDistance = GatherTreeNode.get_tree_leaves_further_than_distance(pruned, threat.armyAnalysis.aMap, threat.turns - flipThingy, survivalThreshold, sumPruned)
                            anyLeafIsSameDistAsThreat = len(leavesGreaterThanDistance) > 0
                            if anyLeafIsSameDistAsThreat:
                                flags = f'leafDist {flags}'
                            else:
                                leavesGreaterThanBlockDistance = GatherTreeNode.get_tree_leaves_further_than_distance(pruned, threat.armyAnalysis.aMap, saveTurns - flipThingy - 1)
                                if len(leavesGreaterThanBlockDistance) > 0:
                                    outputDefenseCriticalTileSet.update([n.tile for n in leavesGreaterThanBlockDistance])

                            if sumPrunedTurns >= threat.turns or anyLeafIsSameDistAsThreat:
                                if interceptMove is not None:
                                    bot.info(f'Must def, int move {interceptMove} (prunedT {sumPrunedTurns}, threat {threat.turns}, anyLeafIsSameDistAsThreat {anyLeafIsSameDistAsThreat})')
                                    return interceptMove, interceptPath

                                pruned = [node.deep_clone() for node in gatherNodes]
                                sumPrunedTurns, sumPruned, pruned = Gather.prune_mst_to_max_army_per_turn_with_values(
                                    pruned,
                                    survivalThreshold,
                                    bot.general.player,
                                    MapBase.get_teams_array(bot._map),
                                    preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                                    viewInfo=bot.viewInfo)

                                move_closest_value_func = bot.get_defense_tree_move_prio_func(threat, anyLeafIsSameDistAsThreat, printDebug=DebugHelper.IS_DEBUGGING)
                                bot.redGatherTreeNodes = gatherNodes

                                bot.gatherNodes = pruned
                                move = bot.get_tree_move_default(pruned, move_closest_value_func)
                                bot.communicate_threat_to_ally(threat, sumPruned, pruned)
                                bot.info(
                                    f'{flags}GathDefRaw-{str(threat.path.start.tile)}@{str(threat.path.tail.tile)}:  {move} val {valueGathered:.1f}/p{sumPruned:.1f}/{survivalThreshold} turns {turnsUsed}/p{sumPrunedTurns}/{threat.turns} offs{distOffsetNOWUNUSED}')
                                return move, savePath
                            else:
                                bot.communicate_threat_to_ally(threat, sumPruned, pruned)
                                isRealThreat = False
                                if not bot.best_defense_leaves:
                                    bot.best_defense_leaves = GatherTreeNode.get_tree_leaves(pruned)
                                    bot.set_defensive_blocks_against(threat)

                                if sumPrunedTurns >= threat.turns - 2:
                                    if interceptMove is not None:
                                        bot.info(f'Soon def, int move?? {interceptMove} (prunedT {sumPrunedTurns}, threat {threat.turns}, anyLeafIsSameDistAsThreat {anyLeafIsSameDistAsThreat})')

                                    def addPrunedDefenseToDefenseNegatives(tn: GatherTreeNode):
                                        if bot.board_analysis.intergeneral_analysis.is_choke(tn.tile) or threat.armyAnalysis.is_choke(tn.tile):
                                            logbook.info(f'    outputDefenseCriticalTileSet SKIPPING CHOKE {str(tn.tile)}')
                                        else:
                                            logbook.info(f'    outputDefenseCriticalTileSet adding {str(tn.tile)}')
                                            outputDefenseCriticalTileSet.add(tn.tile)

                                    GatherTreeNode.foreach_tree_node(pruned, addPrunedDefenseToDefenseNegatives)

                                    if bot.territories.is_tile_in_friendly_territory(threat.path.start.tile):
                                        logbook.info(f'get_defense_moves setting targetingArmy to threat in friendly territory {str(threat.path.start.tile)}')
                                        bot.targetingArmy = bot.get_army_at(threat.path.start.tile)

                                    bot.viewInfo.add_info_line(f'  DEF NEG ADD - prune t{sumPrunedTurns} < threat.turns - 3 {threat.turns - 3} (threatVal {survivalThreshold} v pruneVal {sumPruned:.1f})')

                abandonDefenseThreshold = survivalThreshold * 0.8 - 3 - threat.turns
                if len(bot._map.players) == 2 and bot._map.turn > 250 and not threatMovingWrongWay:
                    abandonDefenseThreshold = survivalThreshold * 0.92 - threat.turns // 2
                if bot._map.players[threat.threatPlayer].knowsKingLocation:
                    abandonDefenseThreshold = survivalThreshold * 0.96 - threat.turns // 4 - 1

                if threat.path.tail.tile.isCity:
                    abandonDefenseThreshold = survivalThreshold

                if valueGathered < survivalThreshold - 1:
                    bot.communicate_threat_to_ally(threat, valueGathered, gatherNodes)
                    extraTurns = 1
                    pruneToValuePerTurn = False
                    if threat.path.tail.tile.isGeneral:
                        flags = f'DEAD {flags}'
                        if raceChance > 0.1 and raceEnemyKingKillPath is not None:
                            bot.info(f'DEAD: RACING BECAUSE WE ARE DEAD WITH A NON-ZERO RACE KILL CHANCE')
                            return raceEnemyKingKillPath.get_first_move(), raceEnemyKingKillPath
                    else:
                        flags = f'CAP {flags}'
                        pruneToValuePerTurn = True
                        extraTurns = 12
                        survivalThreshold += extraTurns // 2

                    with bot.perf_timer.begin_move_event(f'+{extraTurns} Def Threat Gather {threat.path.start.tile}@{threat.path.tail.tile}'):
                        altMove, altValueGathered, altTurnsUsed, altGatherNodes = bot.get_gather_to_threat_path(
                            threat,
                            requiredContribution=survivalThreshold,
                            additionalNegatives=additionalNegatives,
                            addlTurns=extraTurns)

                        if pruneToValuePerTurn and altGatherNodes is not None:
                            sumPrunedTurns, sumPruned, altGatherNodes = Gather.prune_mst_to_army_with_values(
                                altGatherNodes,
                                survivalThreshold + 1,
                                bot.general.player,
                                MapBase.get_teams_array(bot._map),
                                bot._map.turn,
                                viewInfo=bot.viewInfo,
                                preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                                noLog=not DebugHelper.IS_DEBUGGING)
                            valFunc = bot.get_defense_tree_move_prio_func(threat, anyLeafIsSameDistAsThreat=False, printDebug=DebugHelper.IS_DEBUGGING)
                            altMove = bot.get_tree_move_default(altGatherNodes, valFunc)
                    if altMove is not None:
                        directlyAttacksDest = altMove.dest == threat.path.start.tile
                        if directlyAttacksDest or gatherNodes is None or not bot.is_2v2_teammate_still_alive():
                            if altValueGathered >= survivalThreshold:
                                bot.redGatherTreeNodes = gatherNodes
                                move = altMove
                                valueGathered = altValueGathered
                                turnsUsed = altTurnsUsed
                                gatherNodes = altGatherNodes

                isGatherMoveFromBackwards = bot.is_move_towards_enemy(move)
                isGatherMoveFromBackwards = False
                if not isRealThreat and (not isGatherMoveFromBackwards or move is None or bot.detect_repetition_tile(move.source)):
                    if move is None:
                        flags = f'waitNONE {flags}'
                    elif move is not None and bot.detect_repetition_tile(move.source):
                        flags = f'rep {flags}'
                    else:
                        flags = f'wait {flags}'
                    bot.redGatherTreeNodes = gatherNodes
                    bot.gatherNodes = None

                bot.info(
                    f'{flags}GathDef-{str(threat.path.start.tile)}@{str(threat.path.tail.tile)}:  {move} val {valueGathered:.1f}/{survivalThreshold} turns {turnsUsed}/{threat.turns} (abandThresh {abandonDefenseThreshold:.0f} offs{distOffsetNOWUNUSED}')
                if isRealThreat or bot.detect_repetition_tile(move.source, turns=8, numReps=3):
                    realThreats.append(threat)
                    if threat.turns < 7:
                        bot.increment_attack_counts(threat.path.tail.tile)

                if valueGathered > abandonDefenseThreshold or (bot.is_2v2_teammate_still_alive() and len(additionalNegatives) == 0):
                    if isRealThreat:
                        bot.curPath = None
                        bot.gatherNodes = gatherNodes
                        return move, savePath

                    if isGatherMoveFromBackwards and not bot.detect_repetition_tile(move.source):
                        movesToMakeAnyway.append(move)
                else:
                    bot.info(f'aband def bcuz ? valueGathered {valueGathered:.1f} <= abandonDefenseThreshold {abandonDefenseThreshold:.1f}')

            if not isRealThreat or isEconThreat:
                continue

            altKillOffset = 0
            if not bot.targetPlayerExpectedGeneralLocation.isGeneral:
                altKillOffset = 5 + int(len(bot.targetPlayerObj.tiles) ** 0.5)
                logbook.info(f'altKillOffset {altKillOffset} because dont know enemy gen position for sure')
            with bot.perf_timer.begin_move_event(
                    f"ATTEMPTING TO FIND KILL ON ENEMY KING UNDISCOVERED SINCE WE CANNOT SAVE OURSELVES, TURNS {threat.turns - 1}:"):
                altKingKillPath = SearchUtils.dest_breadth_first_target(
                    bot._map,
                    [bot.targetPlayerExpectedGeneralLocation],
                    12,
                    0.1,
                    threat.turns + 1,
                    outputDefenseCriticalTileSet,
                    searchingPlayer=bot.general.player,
                    dontEvacCities=False)

                if altKingKillPath is not None:
                    logbook.info(
                        f"   Did find a killpath on enemy gen / undiscovered {str(altKingKillPath)}")
                    wrpPath = None
                    if not altKingKillPath.tail.tile.isGeneral:
                        wrpPath = bot.get_optimal_exploration(threat.turns, outputDefenseCriticalTileSet, maxTime=0.020, includeCities=False)
                        if wrpPath is not None:
                            for t in wrpPath.tileList:
                                if t in bot.targetPlayerExpectedGeneralLocation.adjacents:
                                    altKingKillPath = wrpPath
                                    bot.info(f'WRP KING KILL {wrpPath}')
                                    r, g, b = Colors.GOLD
                                    bot.viewInfo.color_path(PathColorer(
                                        wrpPath,
                                        r, g, b,
                                        255, 0
                                    ))
                                    break
                            if altKingKillPath != wrpPath:
                                logbook.info(f'wrpPath was {wrpPath}')

                    if (raceEnemyKingKillPath is None or (raceEnemyKingKillPath.length >= threat.turns and wrpPath is None)) and altKingKillPath.length + altKillOffset < threat.turns:
                        bot.info(f"{flags} altKingKillPath {str(altKingKillPath)} altKillOffset {altKillOffset}")
                        bot.viewInfo.color_path(PathColorer(altKingKillPath, 122, 97, 97, 255, 10, 200))
                        return bot.get_first_path_move(altKingKillPath), savePath
                    elif wrpPath is not None:
                        logbook.info("   wrpPath already existing, will not use the above.")
                        bot.info(f"{flags} wrpPath {str(wrpPath)} altKillOffset {altKillOffset}")
                        bot.viewInfo.color_path(PathColorer(wrpPath, 152, 97, 97, 255, 10, 200))
                        return bot.get_first_path_move(wrpPath), savePath
                    elif raceEnemyKingKillPath is not None:
                        logbook.info("   raceEnemyKingKillPath already existing, will not use the above.")
                        bot.info(f"{flags} raceEnemyKingKillPath {str(raceEnemyKingKillPath)} altKillOffset {altKillOffset}")
                        bot.viewInfo.color_path(PathColorer(raceEnemyKingKillPath, 152, 97, 97, 255, 10, 200))
                        return bot.get_first_path_move(raceEnemyKingKillPath), savePath

            if altKingKillPath is not None:
                if raceEnemyKingKillPath is None or raceEnemyKingKillPath.length > threat.turns:
                    bot.info(
                        f"{flags} altKingKillPath (long {altKingKillPath.length} vs threat {threat.turns}) {str(altKingKillPath)}")
                    bot.viewInfo.color_path(PathColorer(altKingKillPath, 122, 97, 97, 255, 10, 200))
                    return bot.get_first_path_move(altKingKillPath), savePath
                elif raceEnemyKingKillPath is not None:
                    logbook.info("   raceEnemyKingKillPath already existing, will not use the above.")
                    bot.info(
                        f"{flags} raceEnemyKingKillPath (long {altKingKillPath.length} vs threat {threat.turns}) {str(raceEnemyKingKillPath)}")
                    bot.viewInfo.color_path(PathColorer(raceEnemyKingKillPath, 152, 97, 97, 255, 10, 200))
                    return bot.get_first_path_move(raceEnemyKingKillPath), savePath

        if len(movesToMakeAnyway) > 0:
            return movesToMakeAnyway[-1], None

        if len(realThreats) == 0:
            return None, None

        for threat in realThreats:
            if threat.path.tail.tile.isGeneral:
                if not bot.targetPlayerExpectedGeneralLocation.isGeneral:
                    explorePath = bot.get_optimal_exploration(max(5, threat.turns))
                    if explorePath is not None:
                        bot.info(f'DEAD EXPLORE {str(explorePath)}')
                        return bot.get_first_path_move(explorePath), explorePath
                else:
                    bot.get_gather_to_target_tile(bot.targetPlayerExpectedGeneralLocation, 1.0, threat.turns)

        return None, None

    @staticmethod
    def build_intercept_plans(bot, negTiles: typing.Set[Tile] | None = None) -> typing.Dict[Tile, typing.Any]:
        interceptions: typing.Dict[Tile, typing.Any] = {}

        bot.blocking_tile_info: typing.Dict[Tile, ThreatBlockInfo] = {}

        with bot.perf_timer.begin_move_event('INTERCEPTIONS (will be overridden below)') as interceptionsEvent:
            with bot.perf_timer.begin_move_event('dangerAnalyzer.get_threats_grouped_by_tile'):
                threatsByTile = bot.dangerAnalyzer.get_threats_grouped_by_tile(
                    bot.armyTracker.armies,
                    includePotentialThreat=True,
                    includeVisionThreat=False,
                    alwaysIncludeArmy=bot.targetingArmy,
                    includeArmiesWithThreats=True,
                    alwaysIncludeRecentlyMoved=True)

            threatsSorted = sorted(threatsByTile.items(), key=lambda tuple: (
                SearchUtils.any_where(tuple[1], lambda t: t.threatType == ThreatType.Kill),
                bot.get_army_at(tuple[0]).last_seen_turn if not tuple[0].visible else 100000,
                bot.get_army_at(tuple[0]).last_moved_turn,
                tuple[0].army
            ), reverse=True)

            threatsWeCareAbout = []
            threatsWeCareAboutByTile = {}

            limit = 4
            timeCut = 0.035
            if bot.is_lag_massive_map:
                timeCut = 0.02
                limit = 2

            skippedIntercepts = []
            start = time.perf_counter()
            isFfa = bot.is_ffa_situation()

            with bot.perf_timer.begin_move_event(f'INT Ensure analysis\''):
                for tile, threats in threatsSorted:
                    if len(threats) == 0:
                        continue

                    threatArmy = bot.get_army_at(tile)

                    threatPlayer = threats[0].threatPlayer
                    if isFfa and bot._map.players[threatPlayer].aggression_factor < 200 and threatPlayer != bot.targetPlayer and not tile.visible:
                        skippedIntercepts.append(tile)
                        continue

                    if isFfa and bot._map.players[threatPlayer].aggression_factor < 50 and not tile.visible:
                        skippedIntercepts.append(tile)
                        continue

                    isCloseThreat = threats[0].turns <= bot.target_player_gather_path.length / 4 and bot.board_analysis.intergeneral_analysis.aMap.raw[tile.tile_index] < bot.target_player_gather_path.length / 2

                    if isFfa and threatArmy.last_seen_turn < bot._map.turn - 4 and not isCloseThreat:
                        skippedIntercepts.append(tile)
                        continue

                    if bot._map.turn - threatArmy.last_seen_turn > max(1.0, bot.target_player_gather_path.length / 5) and not isCloseThreat:
                        skippedIntercepts.append(tile)
                        continue

                    if not bot._map.is_player_on_team_with(threats[0].threatPlayer, bot.targetPlayer) and bot.targetPlayer != -1 and not bot.territories.is_tile_in_friendly_territory(tile):
                        skippedIntercepts.append(tile)
                        continue

                    if len(threatsWeCareAbout) >= limit:
                        skippedIntercepts.append(tile)
                        continue
                    if time.perf_counter() - start > timeCut:
                        bot.info(f'  INTERCEPT BREAKING EARLY AFTER {time.perf_counter() - start:.4f}s BUILDING ANALYSIS\'')
                        break

                    threatsIncluded = []

                    with bot.perf_timer.begin_move_event(f'INT @{str(tile)} Ensure threat army analysis (will get overridden') as moveEvent:
                        num = 0
                        for threat in threats:
                            if threat.turns > 14 and time.perf_counter() - start > 0.02:
                                bot.info(f'  time constraints skipping threat {threat}')
                                continue

                            if threat.turns > 40:
                                bot.info(f'  massive length skipping threat {threat}')
                                continue

                            threatsIncluded.append(threat)
                            if bot.army_interceptor.ensure_threat_army_analysis(threat):
                                num += 1
                        moveEvent.event_name = f'INT @{str(tile)} Analysis ({num} threats)'
                    if num > 0:
                        threatsWeCareAbout.append((tile, threatsIncluded))
                        threatsWeCareAboutByTile[tile] = threatsIncluded

            for tile, threats in threatsWeCareAbout:
                if len(threats) == 0:
                    continue

                if not bot._map.is_player_on_team_with(threats[0].threatPlayer, bot.targetPlayer) and bot.targetPlayer != -1 and not bot.territories.is_tile_in_friendly_territory(tile):
                    continue

                with bot.perf_timer.begin_move_event(f'INT @{str(tile)} Tile Block'):
                    blockingTiles = bot.army_interceptor.get_intercept_blocking_tiles_for_split_hinting(tile, threatsWeCareAboutByTile, negTiles)

                    if len(blockingTiles) > 0:
                        bot.viewInfo.add_info_line(f'for threat {str(tile)}, blocking tiles were {"  ".join([str(v) for v in blockingTiles.values()])}')

                    if SearchUtils.any_where(threats, lambda t: t.threatType == ThreatType.Kill):
                        bot.blocking_tile_info = blockingTiles

                    blocks = blockingTiles
                    if blocks is None:
                        blocks = bot.blocking_tile_info
                    elif blocks != bot.blocking_tile_info:
                        for t, values in bot.blocking_tile_info.items():
                            existing = blocks.get(t, None)
                            if not existing:
                                blocks[t] = values
                            else:
                                for blockedDest in values.blocked_destinations:
                                    existing.add_blocked_destination(blockedDest)

                with bot.perf_timer.begin_move_event(f'INT @{str(tile)} Calc'):
                    shouldBypass = bot.should_bypass_army_danger_due_to_last_move_turn(tile)
                    if shouldBypass and len(interceptions) > 0:
                        army = bot.armyTracker.get_or_create_army_at(tile)
                        bot.viewInfo.add_info_line(f'skip int dngr from{str(tile)} last_seen {army.last_seen_turn}, last_moved {army.last_moved_turn}')
                        continue
                    plan = bot.army_interceptor.get_interception_plan(threats, turnsLeftInCycle=bot.timings.get_turns_left_in_cycle(bot._map.turn), otherThreatsBlockingTiles=blocks)
                    if plan is not None:
                        interceptions[tile] = plan

            interceptionsEvent.event_name = f'INTERCEPTIONS ({len(threatsWeCareAboutByTile)}, skipped {len(skippedIntercepts)} tiles)'

        if len(skippedIntercepts) > 0:
            bot.viewInfo.add_info_line(f'SKIPPED {len(skippedIntercepts)} INTERCEPTS, OVER LIMIT {limit}! Skipped: {" - ".join([str(t) for t in skippedIntercepts])}')

        return interceptions

    @staticmethod
    def get_gather_to_threat_paths(
            bot,
            threats: typing.List[ThreatObj],
            force_turns_up_threat_path=0,
            gatherMax: bool = True,
            shouldLog: bool = False,
            addlTurns: int = 0,
            requiredContribution: int | None = None,
            additionalNegatives: typing.Set[Tile] | None = None,
            interceptArmy: bool = False,
            timeLimit: float | None = None
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        """
        returns move, value, turnsUsed, gatherNodes

        @param threats:
        @param force_turns_up_threat_path:
        @param gatherMax: Sets targetArmy to -1 in the gather, allowing the gather to return less than the threat value.
        @param shouldLog:
        @param addlTurns: if you want to gather longer than the threat, for final save.
        @param requiredContribution: replaces the threat.threatValue as the required army contribution if passed. Does nothing if gatherMax is True.
        @param additionalNegatives:
        @return: move, value, turnsUsed, gatherNodes
        """

        if requiredContribution is None:
            requiredContribution = threats[0].threatValue

        gatherDepth = threats[0].path.length - 1 + addlTurns
        distDict = threats[0].convert_to_dist_dict(allowNonChoke=force_turns_up_threat_path != 0, offset=-1 - addlTurns, mapForPriority=bot._map)
        if bot.has_defenseless_modifier:
            for t in [h for h in distDict.keys()]:
                if t.isGeneral:
                    del distDict[t]

        move, value, turnsUsed, gatherNodes = BotDefense.try_threat_gather(
            bot=bot,
            threats=threats,
            distDict=distDict,
            gatherDepth=gatherDepth,
            force_turns_up_threat_path=force_turns_up_threat_path,
            requiredContribution=requiredContribution,
            gatherMax=gatherMax,
            additionalNegatives=additionalNegatives,
            timeLimit=timeLimit,
            shouldLog=shouldLog)

        return move, value, turnsUsed, gatherNodes

    @staticmethod
    def get_gather_to_threat_path(
            bot,
            threat: ThreatObj,
            force_turns_up_threat_path=0,
            gatherMax: bool = True,
            shouldLog: bool = False,
            addlTurns: int = 0,
            requiredContribution: int | None = None,
            additionalNegatives: typing.Set[Tile] | None = None,
            interceptArmy: bool = False,
            timeLimit: float | None = None
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        return bot.get_gather_to_threat_paths(
            [threat],
            force_turns_up_threat_path,
            gatherMax,
            shouldLog,
            addlTurns,
            requiredContribution,
            additionalNegatives,
            interceptArmy=interceptArmy,
            timeLimit=timeLimit
        )

    @staticmethod
    def try_threat_gather(
            bot,
            threats: typing.List[ThreatObj],
            distDict,
            gatherDepth,
            force_turns_up_threat_path,
            requiredContribution,
            gatherMax,
            additionalNegatives,
            timeLimit,
            pruneDepth: int | None = None,
            shouldLog: bool = False,
            fastMode: bool = False
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:

        # for tile in list(distDict.keys()):
        #     if tile not in commonInterceptPoints:
        #         del distDict[tile]

        if bot._map.is_player_on_team_with(threats[0].path.start.tile.player, bot.general.player):
            raise AssertionError(f'threat paths should start with enemy tile, not friendly tile. Path {str(threats[0].path)}')

        threatDistMap = None
        for threat in threats:
            tail = threat.path.tail
            for i in range(force_turns_up_threat_path):
                if tail is not None:
                    # self.viewInfo.add_targeted_tile(tail.tile, TargetStyle.GREEN)
                    distDict.pop(tail.tile, None)
                    tail = tail.prev
            threatDistMap = threat.armyAnalysis.aMap

        # for tile in distDict.keys():
        #     logbook.info(f'common intercept {str(tile)} at dist {distDict[tile]}')
        #     self.viewInfo.add_targeted_tile(tile, TargetStyle.GOLD, radiusReduction=9)

        move_closest_value_func = None
        if force_turns_up_threat_path == 0:
            move_closest_value_func = bot.get_defense_tree_move_prio_func(threats[0])

        survivalThreshold = requiredContribution

        if survivalThreshold is None:
            survivalThreshold = threats[0].threatValue

        targetArmy = survivalThreshold
        if gatherMax:
            targetArmy = -1

        negatives = set()
        # if force_turns_up_threat_path == 0:
        for threat in threats:
            negatives.update(threat.path.tileSet)
            if bot.has_defenseless_modifier and bot.general in negatives and threat.path.tail.tile == bot.general:
                negatives.discard(bot.general)
                targetArmy += 1
            elif threat.path.tail.tile != bot.general:
                if len(bot.get_danger_tiles()) > 0:
                    negatives.add(bot.general)

        if additionalNegatives is not None:
            negatives.update(negatives)

        prioMatrix = MapMatrix(bot._map, 0.0)
        for tile in bot._map.pathable_tiles:
            prioMatrix.raw[tile.tile_index] = 0.0001 * threats[0].armyAnalysis.aMap.raw[tile.tile_index]  # reward distances further from the threats target, pushing us to intercept further up the path. In theory?

        if timeLimit is None:
            if DebugHelper.IS_DEBUGGING:
                timeLimit = 1000
            else:
                timeLimit = 0.05

        move, value, turnsUsed, gatherNodes = bot.get_defensive_gather_to_target_tiles(
            distDict,
            maxTime=timeLimit,
            gatherTurns=gatherDepth,
            targetArmy=targetArmy,
            useTrueValueGathered=False,
            negativeSet=negatives,
            leafMoveSelectionValueFunc=move_closest_value_func,
            includeGatherTreeNodesThatGatherNegative=True,
            priorityMatrix=prioMatrix,
            distPriorityMap=threatDistMap,
            # maximizeArmyGatheredPerTurn=gatherMax,  # this just immediately breaks the whole gather, prunes everything but the largest tile basically.
            shouldLog=shouldLog,
            fastMode=fastMode)

        if pruneDepth is not None and gatherNodes is not None:
            turnsUsed, value, gatherNodes = Gather.prune_mst_to_turns_with_values(
                gatherNodes,
                pruneDepth,
                searchingPlayer=bot.general.player,
                viewInfo=bot.viewInfo if bot.info_render_gather_values else None
            )

            move = bot.get_tree_move_default(gatherNodes)

        logbook.info(f'get_gather_to_threat_path for depth {gatherDepth} force_turns_up_threat_path {force_turns_up_threat_path} returned {move}, val {value} turns {turnsUsed}')
        return move, value, turnsUsed, gatherNodes

    @staticmethod
    def get_gather_to_threat_path_greedy(
            bot,
            threat: ThreatObj,
            force_turns_up_threat_path=0,
            gatherMax: bool = True,
            shouldLog: bool = False
    ) -> typing.Tuple[None | Move, int, int, None | typing.List[GatherTreeNode]]:
        """
        Greedy is faster than the main knapsack version.
        returns move, valueGathered, turnsUsed

        @return:
        """
        gatherDepth = threat.path.length - 1
        distDict = threat.convert_to_dist_dict()
        tail = threat.path.tail
        for i in range(force_turns_up_threat_path):
            if tail is not None:
                # self.viewInfo.add_targeted_tile(tail.tile, TargetStyle.GREEN)
                del distDict[tail.tile]
                tail = tail.prev

        distMap = SearchUtils.build_distance_map_matrix(bot._map, [threat.path.start.tile])

        def move_closest_priority_func(nextTile, currentPriorityObject):
            return nextTile in threat.armyAnalysis.shortestPathWay.tiles, distMap[nextTile]

        def move_closest_value_func(curTile, currentPriorityObject):
            return curTile not in threat.armyAnalysis.shortestPathWay.tiles, 0 - distMap[curTile]

        targetArmy = threat.threatValue
        if gatherMax:
            targetArmy = -1

        move, value, turnsUsed, gatherNodes = bot.get_gather_to_target_tiles_greedy(
            distDict,
            maxTime=0.05,
            gatherTurns=gatherDepth,
            targetArmy=targetArmy,
            useTrueValueGathered=True,
            priorityFunc=move_closest_priority_func,
            valueFunc=move_closest_value_func,
            includeGatherTreeNodesThatGatherNegative=True,
            shouldLog=shouldLog)
        logbook.info(f'get_gather_to_threat_path for depth {gatherDepth} force_turns_up_threat_path {force_turns_up_threat_path} returned {move}, val {value} turns {turnsUsed}')

        return move, value, turnsUsed, gatherNodes

    @staticmethod
    def is_move_safe_against_threats(bot, move: Move):
        threat = bot.threat
        if not threat:
            threat = bot.dangerAnalyzer.fastestPotentialThreat

        if not threat:
            return True

        if threat.threatType != ThreatType.Kill:
            return True

        if move.dest == threat.path.start.tile or (move.dest == threat.path.start.next.tile and len(threat.armyAnalysis.tileDistancesLookup[1]) == 1):
            return True

        if threat.armyAnalysis.is_choke(move.source) and not threat.armyAnalysis.is_choke(move.dest):
            bot.viewInfo.add_info_line(f'not allowing army move out of threat choke {str(move.source)}')
            return False

        if move.source in threat.path.tileSet and move.dest not in threat.path.tileSet:
            bot.viewInfo.add_info_line(f'not allowing army move out of threat path {str(move.source)}')
            return False

        return True

    @staticmethod
    def _is_invalid_defense_intercept_for_threat(bot, interceptPath: TilePlanInterface | Path | None, threat: ThreatObj) -> bool:
        if interceptPath is None:
            return False

        pathStart = interceptPath.start
        if pathStart is None or pathStart.next is None:
            return False

        if not threat.path.tail.tile.isGeneral:
            return False

        return pathStart.tile in threat.path.tileSet

    @staticmethod
    def get_defense_path_option_from_options_if_available(bot, threatInterceptionPlan, threat: ThreatObj) -> typing.Tuple[InterceptionOptionInfo | None, TilePlanInterface | None]:
        # if not self.expansion_plan.includes_intercept:  # or self.expansion_plan.intercept_waiting
        #     return None, None

        interceptPath = bot.expansion_plan.selected_option
        interceptingOption = None
        if interceptPath is not None and isinstance(interceptPath, InterceptionOptionInfo):
            if interceptPath == threatInterceptionPlan.intercept_options.get(interceptPath.length, None):
                interceptingOption = interceptPath
                interceptPath = interceptPath.path
                if interceptingOption not in threatInterceptionPlan.intercept_options.values():
                    return None, None

        if BotDefense._is_invalid_defense_intercept_for_threat(bot, interceptPath, threat):
            bot.viewInfo.add_info_line(f'bypassing selected defense intercept from threatened tile {interceptPath}')
            interceptPath = None
            interceptingOption = None

        if interceptingOption is None:
            interceptPath = None

        includesIntercept = False
        for delayedInterceptOption in bot.expansion_plan.intercept_waiting:
            if threat in threatInterceptionPlan.threats and delayedInterceptOption in threatInterceptionPlan.intercept_options.values():
                if BotDefense._is_invalid_defense_intercept_for_threat(bot, delayedInterceptOption.path, threat):
                    bot.viewInfo.add_info_line(f'bypassing delayed defense intercept from threatened tile {delayedInterceptOption.path}')
                    continue
                interceptPath = delayedInterceptOption.path
                includesIntercept = True
                interceptingOption = delayedInterceptOption
                isDelayed = True
                break

        if interceptingOption is None:
            vt = 0
            at = 0
            for turns, intercept in threatInterceptionPlan.intercept_options.items():
                if BotDefense._is_invalid_defense_intercept_for_threat(bot, intercept.path, threat):
                    bot.info(f'{turns}: bypassing defense intercept from threatened tile {intercept}')
                    continue
                optVt = intercept.econValue / turns
                optAt = intercept.friendly_army_reaching_intercept / turns

                if optVt > vt:
                    vt = optVt
                    at = optAt
                    bot.info(f'{turns}: val/turn {optVt:.2f} > {vt:.2f}, replacing {interceptingOption} with {intercept}')
                    interceptingOption = intercept
                    interceptPath = interceptingOption.path
                elif vt < 1 and optAt > at:
                    vt = optVt
                    at = optAt
                    bot.info(f'{turns}: army/turn {optAt:.2f} > {at:.2f} (vt {optVt:.2f} vs {vt:.2f}), replacing {interceptingOption} with {intercept}')
                    interceptingOption = intercept
                    interceptPath = interceptingOption.path

        if not includesIntercept and interceptingOption in threatInterceptionPlan.intercept_options.values():
            # if interceptingOption.intercepting_army_remaining <= 0:
            if threat.threatValue - interceptingOption.friendly_army_reaching_intercept < 0:
                includesIntercept = True
                interceptingOption = threatInterceptionPlan.get_intercept_option_by_path(interceptPath)
                if interceptingOption is not None:
                    isDelayed = interceptingOption.requiredDelay > 0
            else:
                bot.viewInfo.add_info_line(f'not safe to intercept {threat.threatValue} capture threat w remaining {interceptingOption.friendly_army_reaching_intercept}')
                return None, None

        return interceptPath, interceptingOption

    @staticmethod
    def check_kill_threat_only_defense_interception(bot, threat: ThreatObj) -> typing.Tuple[Move | None, Path | None, InterceptionOptionInfo | None, bool]:
        if not threat.path.tail.tile.isGeneral:
            return None, None, None, False

        if bot.get_elapsed() > 0.06:
            bot.viewInfo.add_info_line(f'BYPASSING DEF SOLO int of {threat.path.start.tile}->{threat.path.tail.tile} due to elapsed {bot.get_elapsed():.3f}')
            return None, None, None, False

        threatInterceptionPlan = bot.army_interceptor.get_interception_plan([threat], bot._map.remainingCycleTurns)
        bestIsDelayed = False
        if threatInterceptionPlan is None or len(threatInterceptionPlan.intercept_options) == 0:
            return None, None, None, bestIsDelayed

        bestInterceptingOption: InterceptionOptionInfo | None = None
        bestInterceptPath: TilePlanInterface | Path | None = None
        bestMove: Move | None = None
        for i in range(threat.turns // 2 + 1):
            isDelayed = False
            interceptingOption = threatInterceptionPlan.intercept_options.get(i, None)
            if interceptingOption is None:
                continue

            interceptPath = interceptingOption.path
            intOptInfo = ''
            if interceptingOption:
                intOptInfo = f' {interceptingOption}'

            if bot.detect_repetition(interceptingOption.path.get_first_move()):
                bot.info(f'DEF SOLO int BYP REP {i} incl{intOptInfo}')
                continue

            if bestInterceptingOption is not None and bestInterceptingOption.econValue / bestInterceptingOption.length >= interceptingOption.econValue / interceptingOption.length:
                continue

            if interceptPath is None:
                continue
            # removed, breaks test_should_not_try_to_expand_with_potential_threat_blocking_tile
            # if interceptPath.tail.tile not in threat.armyAnalysis.shortestPathWay.tiles and not includesIntercept:
            #     return None, None, isDelayed

            tookTooLong = interceptingOption.friendly_army_reaching_intercept < threat.threatValue
            notEnoughDamageBlocked = interceptingOption.friendly_army_reaching_intercept < threat.threatValue
            if interceptingOption is None:
                continue

            isDelayed = interceptingOption.requiredDelay > 0
            # notEnoughDamageBlocked = interceptingOption.damage_blocked < threat.threatValue
            # notEnoughDamageBlocked = False
            armyLeftOver = interceptingOption.intercepting_army_remaining > 0
            if threat.path.tail.tile.isGeneral:
                if tookTooLong or notEnoughDamageBlocked:
                    bot.viewInfo.add_info_line(
                        f'DEF SOLO int BYP {i}: rem ar {interceptingOption.intercepting_army_remaining}, long {"T" if tookTooLong else "F"}, notBlock {"T" if notEnoughDamageBlocked else "F"}, armyLeft {"T" if armyLeftOver else "F"}, {interceptPath}')
                    continue

            bot.viewInfo.color_path(PathColorer(
                interceptPath, 1, 1, 1,
            ))
            bestMove = bot.get_first_path_move(interceptPath)
            bestInterceptingOption = interceptingOption
            bestInterceptPath = interceptPath
            bestIsDelayed = isDelayed

        if bestMove and bestInterceptingOption:
            bot.viewInfo.add_info_line(
                f'DEF SOLO int found {bestInterceptingOption.length}: rem ar {bestInterceptingOption.intercepting_army_remaining}, {bestInterceptPath}')
        else:
            bot.viewInfo.add_info_line(f'DEF SOLO int NO BEST')

        return bestMove, bestInterceptPath, bestInterceptingOption, bestIsDelayed

    @staticmethod
    def should_bypass_army_danger_due_to_last_move_turn(bot, tile: Tile) -> bool:
        army = bot.get_army_at(tile)
        shouldBypass = army.last_seen_turn < bot._map.turn - 6 and not army.tile.visible
        shouldBypass = shouldBypass or (army.tile.isCity and army.last_moved_turn < bot._map.turn - 3)

        return shouldBypass

    @staticmethod
    def should_force_gather_to_enemy_tiles(bot) -> bool:
        """
        Determine whether we've let too much enemy tiles accumulate near our general,
         and it is getting out of hand and we should spend a cycle just gathering to kill them.
        """
        forceGatherToEnemy = False
        scaryDistance = 3
        if bot.shortest_path_to_target_player is not None:
            scaryDistance = bot.shortest_path_to_target_player.length // 3 + 2

        thresh = 1.3
        numEnemyTerritoryNearGen = bot.count_enemy_territory_near_tile(bot.general, distance=scaryDistance)
        enemyTileNearGenRatio = numEnemyTerritoryNearGen / max(1.0, scaryDistance)
        if enemyTileNearGenRatio > thresh:
            forceGatherToEnemy = True

        bot.viewInfo.add_info_line(
            f'forceEn={forceGatherToEnemy} (near {numEnemyTerritoryNearGen}, dist {scaryDistance}, rat {enemyTileNearGenRatio:.2f} vs thresh {thresh:.2f})')
        return forceGatherToEnemy

    @staticmethod
    def check_for_danger_tile_moves(bot) -> Move | None:
        dangerTiles = bot.get_danger_tiles()
        if len(dangerTiles) == 0 or bot.all_in_losing_counter > 15:
            return None

        for tile in dangerTiles:
            bot.viewInfo.add_targeted_tile(tile, TargetStyle.RED)
            negTiles = []
            if bot.curPath is not None:
                negTiles = [tile for tile in bot.curPath.tileSet]
            armyToSearch = bot.get_target_army_inc_adjacent_enemy(tile)
            killPath = SearchUtils.dest_breadth_first_target(
                bot._map,
                [tile],
                armyToSearch,
                0.1,
                3,
                negTiles,
                searchingPlayer=bot.general.player,
                dontEvacCities=False)

            if killPath is None:
                continue

            move = bot.get_first_path_move(killPath)
            if bot.is_move_safe_valid(move):
                if bot.detect_repetition(move, 4, 2):
                    bot.info(
                        f"Danger tile kill resulted in repetitions, fuck it. {str(tile)} {str(killPath)}")
                    return None

                bot.info(
                    f"Depth {killPath.length} dest bfs kill on danger tile {str(tile)} {str(killPath)}")
                logbook.info(f'Setting targetingArmy to {str(tile)} in check_for_danger_tiles_move')
                bot.targetingArmy = bot.get_army_at(tile)
                return move

    @staticmethod
    def find_sketchy_fog_flank_from_enemy_in_play_area(bot) -> Path | None:
        """
        Hunts for a sketchy flank attack point the enemy might be inclined to abuse from a city/general,
        and returns it as a fog-only path to the enemy attack source.
        """

        launchPoints = [bot.targetPlayerExpectedGeneralLocation]
        for c in bot.targetPlayerObj.cities:
            if not c.discovered:
                continue
            if not bot.territories.is_tile_in_enemy_territory(c):
                continue
            launchPoints.append(c)

        distCap = bot.board_analysis.inter_general_distance + 7
        depth = min(30, distCap)

        distMatrix = SearchUtils.build_distance_map_matrix(bot._map, [bot.general])

        sketchyPath = bot.find_flank_opportunity(
            targetPlayer=bot.general.player,
            flankingPlayer=bot.targetPlayer,
            flankPlayerLaunchPoints=launchPoints,
            depth=depth,
            targetDistMap=distMatrix,
            validEmergencePointMatrix=bot.board_analysis.flank_danger_play_area_matrix)

        return sketchyPath

    @staticmethod
    def find_sketchiest_fog_flank_from_enemy(bot) -> Path | None:
        """
        Hunts for a sketchy flank attack point the enemy might be inclined to abuse from a city/general,
        and returns it as a fog-only path to the enemy attack source.
        """
        territoryDists = bot.territories.territoryDistances[bot.general.player]

        enemyLaunchPoints = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=5, cutoffEmergenceRatio=0.25)
        for c in bot.targetPlayerObj.cities:
            if c.visible:
                continue
            enemyLaunchPoints.append(c)

        distCap = bot.board_analysis.inter_general_distance + 15
        depth = min(35, distCap)

        missingCities = bot.opponent_tracker.get_team_unknown_city_count_by_player(bot.targetPlayer)

        def valueFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            if tile not in bot.board_analysis.flankable_fog_area_matrix:
                return None

            if prioVals:
                dist, negSumTerritoryDists, _, usedUnkCities = prioVals

                return 0 - bot.board_analysis.intergeneral_analysis.aMap[tile], 0 - negSumTerritoryDists, dist
            return None

        def prioFunc(tile: Tile, prioVals) -> typing.Tuple | None:
            dist, negSumTerritoryDists, _, usedUnkCities = prioVals

            if tile.isObstacle:
                if tile.visible:
                    return None
                if tile.isMountain:
                    return None
                wallBreachScore = bot.board_analysis.get_wall_breach_expandability(tile, bot.targetPlayer)
                if not wallBreachScore or wallBreachScore < 3:
                    return None
                usedUnkCities += 1

                if usedUnkCities > missingCities:
                    return None

            if tile not in bot.board_analysis.flankable_fog_area_matrix:
                return None

            return dist + 1, negSumTerritoryDists - territoryDists[tile], bot.board_analysis.intergeneral_analysis.aMap[tile], usedUnkCities

        skip = set()

        for tile in bot._map.get_all_tiles():
            if tile not in bot.board_analysis.flankable_fog_area_matrix:
                skip.add(tile)

        startTiles = {}
        for tile in enemyLaunchPoints:
            startTiles[tile] = ((0, 0, 0, 0), 0)

        path = SearchUtils.breadth_first_dynamic_max(
            bot._map,
            startTiles,
            valueFunc=valueFunc,
            priorityFunc=prioFunc,
            skipTiles=skip,
            maxTime=0.1,
            maxDepth=depth,
            noNeutralCities=False,
            useGlobalVisitedSet=True,
            searchingPlayer=bot.targetPlayer,
            noNeutralUndiscoveredObstacles=False,
            skipFunc=lambda t, _: False,
            noLog=True)

        if not path or path.length < 3:
            return None

        return path

    @staticmethod
    def find_flank_opportunity(
            bot,
            targetPlayer: int,
            flankingPlayer: int,
            flankPlayerLaunchPoints: typing.List[Tile],
            depth: int,
            targetDistMap,
            validEmergencePointMatrix,
            maxFogRange: int = -1
    ) -> Path | None:
        if maxFogRange == -1:
            maxFogRange = bot.board_analysis.inter_general_distance + 2

        def prioFunc(curTile: Tile, prioObj):
            dist, negMaxPerTurn, zoningPenalty, fogTileCount, sequentialNonFog, totalNonFog, minDistFogEmergence, hadPossibleVision, hadDefiniteVision, fromTile = prioObj

            hasPossibleVision = SearchUtils.any_where(curTile.adjacents, lambda t: t.player == targetPlayer or (not curTile.visible and bot.territories.territoryMap[t] == targetPlayer))
            hasDefiniteVision = SearchUtils.any_where(curTile.adjacents, lambda t: t.player == targetPlayer)

            if fromTile is not None:
                hasPossibleFromVision = SearchUtils.any_where(fromTile.adjacents, lambda t: t.player == targetPlayer or (not fromTile.visible and bot.territories.territoryMap[t] == targetPlayer))
                hasDefiniteFromVision = SearchUtils.any_where(fromTile.adjacents, lambda t: t.player == targetPlayer)

                if not hasPossibleFromVision and not hasDefiniteFromVision and hasDefiniteVision:
                    return None

            if not hasPossibleVision:
                fogTileCount += 1
                sequentialNonFog = 0
            elif not hasDefiniteVision:
                fogTileCount += 0.5
                sequentialNonFog += 0.5
                minDistFogEmergence = min(dist + 1, minDistFogEmergence)
            else:
                sequentialNonFog += 1
                totalNonFog += 1
                minDistFogEmergence = min(dist, minDistFogEmergence)

            zoningPenalty = 1 / (1 + bot.get_distance_from_board_center(curTile, center_ratio=0.0))

            dist += 1

            return dist, 0 - fogTileCount / dist, zoningPenalty, fogTileCount, sequentialNonFog, totalNonFog, minDistFogEmergence, hasPossibleVision, hasDefiniteVision, curTile

        def valueFunc(curTile: Tile, prioObj):
            dist, negMaxPerTurn, zoningPenalty, fogTileCount, sequentialNonFog, totalNonFog, minDistFogEmergence, hasPossibleVision, hasDefiniteVision, fromTile = prioObj

            if fromTile is not None and targetDistMap[fromTile] < targetDistMap[curTile]:
                return None
            if sequentialNonFog > 0:
                return None
            if totalNonFog > maxFogRange:
                return None
            if validEmergencePointMatrix is not None and curTile not in validEmergencePointMatrix:
                return None

            return minDistFogEmergence - zoningPenalty

        startTiles = {}
        for tile in flankPlayerLaunchPoints:
            startTiles[tile] = ((0, 0, 0, 0, 0, 0, 1000, 0, 0, None), 0)
        flankPath = SearchUtils.breadth_first_dynamic_max(
            bot._map,
            startTiles,
            priorityFunc=prioFunc,
            valueFunc=valueFunc,
            noNeutralCities=False,
            skipFunc=lambda t, prio: t.isUndiscoveredObstacle or t.visible,
            maxDepth=depth,
            searchingPlayer=flankingPlayer,
        )

        if flankPath is not None:
            flankPath = flankPath.get_reversed()

        return flankPath

    @staticmethod
    def get_defense_tree_move_prio_func_old(
            bot,
            threat: ThreatObj,
            anyLeafIsSameDistAsThreat: bool = False,
            printDebug: bool = False
    ) -> typing.Callable[[Tile, typing.Any], typing.Any]:
        threatenedTileDistMap = threat.armyAnalysis.aMap
        threatDistMap = threat.armyAnalysis.bMap
        threatDist = threatenedTileDistMap.raw[threat.path.start.tile.tile_index]

        shortestTiles = threat.armyAnalysis.shortestPathWay.tiles

        def move_closest_negative_value_func(curTile: Tile, currentPriorityObject):
            toTile = None
            lastIsntDelayable = False
            lastIsInterceptingIn1 = False
            lastNotInShortest = False
            lastRootHeur = 0
            lastNegClosenessToThreat = -1000
            lastArmy = 0
            rootDistToThreat = threatDistMap.raw[curTile.tile_index]
            depth = 0
            if currentPriorityObject is not None:
                lastIsntDelayable, lastIsInterceptingIn1, lastNotInShortest, lastRootHeur, lastNegClosenessToThreat, lastArmy, depth, rootDistToThreat, toTile = currentPriorityObject

            isMovable = curTile in threat.path.start.tile.movable
            isMovableToThreatButNotIntercepting = toTile != threat.path.start.tile and isMovable and threatenedTileDistMap.raw[curTile.tile_index] < threatDist

            closenessToThreat = threatenedTileDistMap.raw[curTile.tile_index]
            inShortest = curTile in shortestTiles
            if threatDist > closenessToThreat and inShortest:
                closenessToThreat = 0 - closenessToThreat

            isInterceptingIn1 = threatDistMap.raw[curTile.tile_index] == 2 and toTile is not None and threatDistMap.raw[toTile.tile_index] == 1

            if isMovableToThreatButNotIntercepting:
                closenessToThreat += 20
            elif isMovable:
                closenessToThreat = 0

            isntDelayableCity = anyLeafIsSameDistAsThreat or not curTile.isCity

            obj = (
                isntDelayableCity,
                isInterceptingIn1 or lastIsInterceptingIn1,
                not inShortest,
                0 - rootDistToThreat + depth,
                0 - closenessToThreat,
                curTile.army,
                depth + 1,
                rootDistToThreat,
                curTile,
            )
            if printDebug and curTile.player == bot.general.player:
                bot.viewInfo.add_info_line(f'{curTile}: {obj}  (isMov {str(isMovable)[0]}, int1 {str(isInterceptingIn1)[0]}, short {str(inShortest)[0]}, mvNotInt {str(isMovableToThreatButNotIntercepting)[0]})')

            return obj

        return move_closest_negative_value_func

    @staticmethod
    def get_defense_tree_move_prio_func(
            bot,
            threat: ThreatObj,
            anyLeafIsSameDistAsThreat: bool = False,
            printDebug: bool = False
    ) -> typing.Callable[[Tile, typing.Any], typing.Any]:
        threatenedTileDistMap = threat.armyAnalysis.aMap
        threatDistMap = threat.armyAnalysis.bMap
        threatDist = threatenedTileDistMap.raw[threat.path.start.tile.tile_index]

        shortestTiles = threat.armyAnalysis.shortestPathWay.tiles

        def move_closest_negative_value_func(curTile: Tile, currentPriorityObject):
            toTile = None
            lastIsntDelayable = False
            lastIsInterceptingIn1 = False
            lastNotInShortest = False
            lastRootHeur = 0
            lastNegClosenessToThreat = -1000
            lastArmy = 0
            rootDistToThreat = threatDistMap.raw[curTile.tile_index]
            depth = 0
            if currentPriorityObject is not None:
                lastIsntDelayable, lastIsInterceptingIn1, lastNotInShortest, lastRootHeur, lastNegClosenessToThreat, lastArmy, depth, rootDistToThreat, toTile = currentPriorityObject

            isMovable = curTile in threat.path.start.tile.movable
            isMovableToThreatButNotIntercepting = toTile != threat.path.start.tile and isMovable and threatenedTileDistMap.raw[curTile.tile_index] < threatDist

            closenessToThreat = threatenedTileDistMap.raw[curTile.tile_index]
            inShortest = curTile in shortestTiles
            if threatDist > closenessToThreat and inShortest:
                closenessToThreat = 0 - closenessToThreat

            isInterceptingIn1 = threatDistMap.raw[curTile.tile_index] == 2 and toTile is not None and threatDistMap.raw[toTile.tile_index] == 1

            if isMovableToThreatButNotIntercepting:
                closenessToThreat += 20
            elif isMovable:
                closenessToThreat = 0

            isntDelayableCity = anyLeafIsSameDistAsThreat or not curTile.isCity

            obj = (
                isntDelayableCity,
                isInterceptingIn1 or lastIsInterceptingIn1,
                not inShortest,
                0 - rootDistToThreat + depth,
                0 - closenessToThreat,
                curTile.army,
                depth + 1,
                rootDistToThreat,
                curTile,
            )
            if printDebug and curTile.player == bot.general.player:
                bot.viewInfo.add_info_line(f'{curTile}: {obj}  (isMov {str(isMovable)[0]}, int1 {str(isInterceptingIn1)[0]}, short {str(inShortest)[0]}, mvNotInt {str(isMovableToThreatButNotIntercepting)[0]})')

            return obj

        return move_closest_negative_value_func

    @staticmethod
    def get_potential_threat_movement_negatives(bot, targetTile: Tile | None = None) -> typing.Set[Tile]:
        """
        Based on an available potential threat path, determine if any tiles are not allowed to move because they would increase risk.

        @param targetTile: Optionally include the target tile that you are calculating moves AGAINST which will allow tile use that would otherwise be blocked if the target is part of the threat.

        @return:
        """
        potThreat = bot.dangerAnalyzer.fastestPotentialThreat
        potNegs = set()

        if potThreat is None:
            return potNegs

        if targetTile is not None and targetTile in potThreat.armyAnalysis.shortestPathWay.tiles:
            return potNegs

        threatArmy = bot.armyTracker.armies.get(potThreat.path.start.tile, None)

        if threatArmy is not None and not threatArmy.tile.visible:
            if potThreat.turns < 7 and bot.targetingArmy is None:
                logbook.info(f'get_potential_threat_movement_negatives setting targetingArmy to {str(threatArmy)} due to potential threat less than 7')
                bot.targetingArmy = threatArmy
            elif threatArmy.last_seen_turn < bot._map.turn - 4 and threatArmy.last_moved_turn < bot._map.turn - 1:
                return potNegs

        shortestSet = set()
        if targetTile is not None:
            targetAnalysis = bot.get_army_analyzer(bot.general, targetTile)
            shortestSet = targetAnalysis.shortestPathWay.tiles

        for tile in potThreat.path.tileList:
            if bot._map.is_tile_friendly(tile) and potThreat.threatValue + tile.army > potThreat.turns and tile not in shortestSet:
                potNegs.add(tile)

        return potNegs

    @staticmethod
    def check_defense_intercept_move(bot, threat: ThreatObj) -> typing.Tuple[Move | None, Path | None, InterceptionOptionInfo | None, bool]:
        threatInterceptionPlan = bot.intercept_plans.get(threat.path.start.tile, None)
        isDelayed = False
        threatTile = threat.path.start.tile
        threatArmy = bot.get_army_at(threatTile)

        isNonAggressor = (bot._map.players[threat.threatPlayer].aggression_factor < 50 and not threatTile.visible)
        tileNotAttacking = (threatArmy.last_moved_turn < bot._map.turn - 2 or threatArmy.last_seen_turn < bot._map.turn - 2)
        if threat.threatPlayer != bot.targetPlayer and not bot._map.is_2v2 and (isNonAggressor or tileNotAttacking or threatArmy.last_seen_turn < bot._map.turn - 6):
            return None, None, None, False

        if threatInterceptionPlan is None or len(threatInterceptionPlan.intercept_options) == 0:
            with bot.perf_timer.begin_move_event(f'def solo interception @ {threat.path.start.tile}'):
                return bot.check_kill_threat_only_defense_interception(threat)

        interceptingOption: InterceptionOptionInfo | None = None
        interceptPath: TilePlanInterface | Path | None = None
        interceptPath, interceptingOption = bot.get_defense_path_option_from_options_if_available(threatInterceptionPlan, threat)
        if interceptPath is None:
            with bot.perf_timer.begin_move_event(f'def solo interception @ {threat.path.start.tile}'):
                return bot.check_kill_threat_only_defense_interception(threat)

        tookTooLong = interceptPath.length > threat.turns
        notEnoughDamageBlocked = False
        armyLeftOver = False
        if interceptingOption is not None:
            isDelayed = interceptingOption.requiredDelay > 0
            notEnoughDamageBlocked = False
            armyLeftOver = threat.threatValue - interceptingOption.friendly_army_reaching_intercept > 0
            if threat.path.tail.tile.isGeneral:
                if tookTooLong or notEnoughDamageBlocked or armyLeftOver:
                    bot.viewInfo.add_info_line(
                        f'DEF int BYP: rem ar {interceptingOption.intercepting_army_remaining}, long {"T" if tookTooLong else "F"}, notBlock {"T" if notEnoughDamageBlocked else "F"}, armyLeft {"T" if armyLeftOver else "F"}, {interceptPath}')
                    if SearchUtils.any_where(threatInterceptionPlan.threats, lambda t: not t.path.tail.tile.isGeneral):
                        with bot.perf_timer.begin_move_event(f'def solo interception @ {threat.path.start.tile}'):
                            return bot.check_kill_threat_only_defense_interception(threat)
                    return None, None, None, False

        bot.viewInfo.color_path(PathColorer(
            interceptPath, 1, 1, 1,
        ))
        intOptInfo = ''
        if interceptingOption:
            intOptInfo = f' {interceptingOption}'
        mv = bot.get_first_path_move(interceptPath)
        if bot.detect_repetition(mv, 6, 3):
            bot.info(f'DEF int REP SKIP... incl{intOptInfo}: long {"T" if tookTooLong else "F"}')
            bot.info(f'    notBlock {"T" if notEnoughDamageBlocked else "F"}, armyLeft {"T" if armyLeftOver else "F"}, {interceptPath}')
            mv = None
        elif bot.detect_repetition(mv, 4, 2):
            bot.curPath = interceptPath.get_subsegment(3)
            bot.info(f'DEF int REP incl{intOptInfo}: long {"T" if tookTooLong else "F"}')
            bot.info(f'    notBlock {"T" if notEnoughDamageBlocked else "F"}, armyLeft {"T" if armyLeftOver else "F"}, {interceptPath}')
        else:
            bot.info(f'DEF int incl{intOptInfo}: long {"T" if tookTooLong else "F"}')
            bot.info(f'    notBlock {"T" if notEnoughDamageBlocked else "F"}, armyLeft {"T" if armyLeftOver else "F"}, {interceptPath}')
        return mv, interceptPath, interceptingOption, isDelayed

    @staticmethod
    def check_defense_hybrid_intercept_moves(bot, threat: ThreatObj, defensePlan: typing.List[GatherTreeNode], missingDefense: int, defenseNegatives: typing.Set[Tile]) -> typing.Tuple[Move | None, Path | None, bool, typing.List[GatherTreeNode]]:
        """
        Returns [replacementMove, replacementPath, isDelayed, updatedDefenseNodes]

        @param threat:
        @param defensePlan:
        @param missingDefense:
        @param defenseNegatives:
        @return:
        """
        threatInterceptionPlan = bot.intercept_plans.get(threat.path.start.tile, None)

        curDefensePlan = defensePlan
        achievedDefense = sum(int(n.value) for n in defensePlan)
        defenseTurns = sum(n.gatherTurns for n in defensePlan)
        totalToSurvive = achievedDefense + missingDefense

        isDelayed = False
        if threatInterceptionPlan is None or len(threatInterceptionPlan.intercept_options) == 0:
            return None, None, isDelayed, defensePlan

        bestOpt = None
        bestEcon = 0.0
        bestAchievedDefense = achievedDefense
        bot.info(f'  def HYBR int base defense {achievedDefense} in {defenseTurns}t (to survive {totalToSurvive} missing def {missingDefense})')
        bestTurns = defenseTurns
        bestSurvives = missingDefense <= 0
        isGeneralThreat = threat.path.tail.tile.isGeneral
        bestRemainingDefense = defensePlan

        for distance, opt in sorted(threatInterceptionPlan.intercept_options.items()):
            if opt.path.start.tile in threat.path.tileSet:
                continue
            if distance != opt.path.length:
                bot.info(f' - HYBR recap int {distance}t {opt.length}o {opt.recapture_turns}r {opt.path.length}l  {opt.best_case_intercept_moves}bc  {opt}')
                continue
            else:
                bot.info(f' + HYBR recap int {distance}t {opt.length}o {opt.recapture_turns}r {opt.path.length}l  {opt.best_case_intercept_moves}bc  {opt}')

            gatherTreenNodesClone = GatherTreeNode.clone_nodes(defensePlan)
            currentAchievedDefense = achievedDefense
            currentGatherTurns = defenseTurns
            currentTotalToSurvive = totalToSurvive

            tookTooLong = opt.length > threat.turns
            if isGeneralThreat:
                if tookTooLong:
                    continue

            forcePrune = opt.tileSet.copy()
            forcePrune.difference_update(n.tile for n in defensePlan)
            turns, val, pruned = Gather.prune_mst_to_turns_with_values(gatherTreenNodesClone, threat.turns - opt.worst_case_intercept_moves, bot.general.player, allowNegative=True, preferPrune=forcePrune, forcePrunePreferPrune=True)
            currentAchievedDefense = val + opt.friendly_army_reaching_intercept
            currentGatherTurns = turns + opt.worst_case_intercept_moves
            betterVt = (currentAchievedDefense > totalToSurvive and currentAchievedDefense / currentGatherTurns > bestAchievedDefense / bestTurns)
            if currentAchievedDefense >= bestAchievedDefense or betterVt:
                bot.info(f'  HYBR int {opt}:')
                bot.info(f'     {currentAchievedDefense:.1f} > {bestAchievedDefense:.1f} ({currentGatherTurns}t vs {bestTurns}t) or {currentAchievedDefense / currentGatherTurns:.2f}vt > {bestAchievedDefense / bestTurns:.2f}vt (w pruned def {val:.1f}/{turns}t {0 if turns == 0.0 else val / turns:.2f}vt)')

                bestTurns = currentGatherTurns
                bestAchievedDefense = currentAchievedDefense
                bestSurvives = bestAchievedDefense >= totalToSurvive
                bestRemainingDefense = pruned
                bestOpt = opt
            elif DebugHelper.IS_DEBUGGING:
                bot.info(f' -HYBR int incl{opt}:')
                bot.info(f'     {currentAchievedDefense:.1f} < {bestAchievedDefense:.1f} ({currentGatherTurns}t vs {bestTurns}t)  and {currentAchievedDefense / currentGatherTurns:.2f}vt < {bestAchievedDefense / bestTurns:.2f}vt (w pruned def {val:.1f}/{turns}t {0 if turns == 0.0 else val / turns:.2f}vt)')

        if bestOpt is not None:
            bot.viewInfo.color_path(PathColorer(
                bestOpt.path, 1, 1, 1,
            ))
            intOptInfo = f' {bestOpt}'
            bot.info(f'DEF HYBR int incl{intOptInfo}: {bestAchievedDefense:.1f}a in {bestTurns}t')

            return bot.get_first_path_move(bestOpt.path), bestOpt.path, isDelayed, bestRemainingDefense

        return None, None, False, bestRemainingDefense

    @staticmethod
    def get_enemy_probable_attack_path(bot, enemyPlayer: int) -> Path | None:
        def valFunc(curTile: Tile, prioObj):
            (dist, negArmySum, sumX, sumY, goalIncrement) = prioObj
            if curTile not in bot.board_analysis.flankable_fog_area_matrix:
                return None
            if not bot._map.is_tile_on_team_with(curTile, enemyPlayer):
                return None
            if curTile.visible:
                return None

            return 0 - negArmySum

        def priorityFunc(nextTile, currentPriorityObject):
            (dist, negArmySum, sumX, sumY, goalIncrement) = currentPriorityObject
            dist += 1

            if bot._map.is_player_on_team_with(nextTile.player, enemyPlayer):
                negArmySum -= nextTile.army
            negArmySum += 1
            negArmySum -= goalIncrement
            return dist, negArmySum, sumX + nextTile.x, sumY + nextTile.y, goalIncrement

        genSet = set()
        genSet.update(bot.player.tiles)

        genTargs = []
        genTargs.append(bot.general)

        for teammate in bot._map.teammates:
            if not bot._map.players[teammate].dead:
                genSet.update(bot._map.players[teammate].tiles)
                genTargs.append(bot._map.players[teammate].general)

        searchLen = 15
        if bot.shortest_path_to_target_player is not None:
            searchLen = bot.shortest_path_to_target_player.length + 1

        startTiles = {}
        for tile in genTargs:
            dist = 0
            negArmySum = goalIncrement = 0

            startTiles[tile] = ((dist, negArmySum, tile.x, tile.y, goalIncrement), 0)

        enPath = SearchUtils.breadth_first_dynamic_max(
            bot._map,
            startTiles,
            valFunc,
            0.1,
            searchLen,
            priorityFunc=priorityFunc,
            noNeutralCities=True,
            noNeutralUndiscoveredObstacles=True,
            negativeTiles=genSet,
            searchingPlayer=enemyPlayer,
            ignoreNonPlayerArmy=True,
            noLog=True)
        if enPath is None or enPath.length < 3:
            return None

        enPath = enPath.get_reversed()
        enPath.calculate_value(enemyPlayer, bot._map.team_ids_by_player_index, genSet, ignoreNonPlayerArmy=True)
        bot.viewInfo.color_path(
            PathColorer(
                enPath,
                255, 190, 120,
                alpha=255,
                alphaDecreaseRate=1
            )
        )

        return enPath

    @staticmethod
    def _get_defensive_spanning_tree(bot, negativeTiles: TileSet, gatherPrioMatrix: MapMatrixInterface[float] | None = None) -> typing.Set[Tile]:
        includes = [bot.general]
        if bot.is_2v2_teammate_still_alive():
            includes.append(bot.teammate_general)
            includes.extend(bot._map.players[bot.teammate].cities)

        includes.extend(bot._map.players[bot.general.player].cities)

        limit = 12
        if len(includes) > limit:
            includes = sorted(includes, key=lambda c: bot.territories.territoryDistances[bot.targetPlayer].raw[c.tile_index] if not c.isGeneral else 0)[:limit]

        distLimit = 50
        if bot.sketchiest_potential_inbound_flank_path:
            distLimit = bot.distance_from_general(bot.sketchiest_potential_inbound_flank_path.tail.tile)
        distLimit = max(distLimit, int(max(bot.distance_from_general(t) for t in includes) * 1.5))

        if distLimit > 50:
            bot.info(f'defensive spanning tree using higher distLimit {distLimit}')

        banned = MapMatrixSet(bot._map)
        for t in bot._map.get_all_tiles():
            if not t.visible:
                banned.raw[t.tile_index] = True

        spanningTreeTiles, unconnectableTiles = MapSpanningUtils.get_max_gather_spanning_tree_set_from_tile_lists(
            bot._map,
            includes,
            banned,
            negativeTiles,
            maxTurns=distLimit,
            gatherPrioMatrix=gatherPrioMatrix,
            searchingPlayer=bot.general.player
        )

        if unconnectableTiles:
            for t in unconnectableTiles:
                bot.viewInfo.add_targeted_tile(t, TargetStyle.PURPLE, radiusReduction=-1)
            bot.viewInfo.add_info_line(f'PURPLE LARGE CIRC = unconnectable defensive spanning tree points.')

        return spanningTreeTiles

    @staticmethod
    def general_move_safe(bot, target, move_half=False):
        dangerTiles = BotDefense.get_general_move_blocking_tiles(bot, target, move_half)
        return len(dangerTiles) == 0

    @staticmethod
    def check_fog_risk(bot):
        bot.high_fog_risk = False
        if bot.targetPlayer == -1:
            return

        cycleTurn = bot.timings.get_turn_in_cycle(bot._map.turn)
        cycleTurnsLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)

        pathWorth = bot.get_player_army_amount_on_path(bot.target_player_gather_path, bot.general.player)
        pushRiskTurns = max(1, cycleTurnsLeft - bot.target_player_gather_path.length)
        bot.fog_risk_amount = 0

        oppStats = bot.opponent_tracker.get_current_cycle_stats_by_player(bot.targetPlayer)
        enGathAmt = 0
        if oppStats is not None:
            fogRisk = bot.opponent_tracker.get_approximate_fog_army_risk(bot.targetPlayer, inTurns=pushRiskTurns)
            enGathAmt = oppStats.approximate_army_gathered_this_cycle
            bot.fog_risk_amount = fogRisk

        numFog = bot.get_undiscovered_count_on_path(bot.target_player_gather_path)
        if numFog > bot.target_player_gather_path.length // 2:
            bot.viewInfo.add_info_line(f'bypassing fog risk due to unknown path')
            return

        if bot.fog_risk_amount > 0:
            if cycleTurnsLeft > bot.target_player_gather_path.length + 5 and bot.fog_risk_amount > pathWorth and bot._map.turn > 80:
                bot.viewInfo.add_info_line(f'high fog risk, fog_risk_amount {bot.fog_risk_amount} in {pushRiskTurns} (gath {enGathAmt}) vs {pathWorth} - {cycleTurnsLeft} vs len {bot.target_player_gather_path.length}')
                bot.high_fog_risk = True
                return

            bot.viewInfo.add_info_line(f'NOT fog risk, fog_risk_amount {bot.fog_risk_amount} in {pushRiskTurns} (gath {enGathAmt}) vs {pathWorth} - {cycleTurnsLeft} vs len {bot.target_player_gather_path.length}')

    @staticmethod
    def get_general_move_blocking_tiles(bot, target: Tile, move_half=False):
        blockingTiles = []

        dangerPaths = BotDefense.get_danger_paths(bot, move_half)

        for dangerPath in dangerPaths:
            dangerTile = dangerPath.start.tile
            genDist = bot._map.euclidDist(dangerTile.x, dangerTile.y, bot.general.x, bot.general.y)
            dangerTileIsTarget = target.x == dangerTile.x and target.y == dangerTile.y
            if dangerTileIsTarget:
                logbook.info(
                    f"ALLOW Enemy tile {dangerTile.x},{dangerTile.y} allowed due to dangerTileIsTarget {dangerTileIsTarget}.")
                continue

            dangerTileForwardMoves = SearchUtils.where(
                dangerTile.movable,
                lambda t: bot.distance_from_general(dangerTile) > bot.distance_from_general(t))

            dangerTileCanOnlyMoveToIntercept = (len(dangerTileForwardMoves) == 1 and genDist > bot._map.euclidDist(dangerTile.x, dangerTile.y, target.x, target.y))

            targetBlocksDangerTile = (
                    (bot.general.x == target.x and bot.general.x == dangerTile.x)
                    or (bot.general.y == target.y and bot.general.y == dangerTile.y)
                    or dangerTileCanOnlyMoveToIntercept
            )

            if targetBlocksDangerTile:
                logbook.info(
                    f"ALLOW Enemy tile {dangerTile.x},{dangerTile.y} allowed due to targetBlocksDangerTile {targetBlocksDangerTile}.")
                continue

            blockingTiles.append(dangerTile)
            logbook.info(
                f"BLOCK Enemy tile {dangerTile.x},{dangerTile.y} is preventing king moves. NOT dangerTileIsTarget {dangerTileIsTarget} or targetBlocksDangerTile {targetBlocksDangerTile}")

        return blockingTiles

    @staticmethod
    def get_danger_tiles(bot, move_half=False) -> typing.Set[Tile]:
        dangerPaths = BotDefense.get_danger_paths(bot, move_half)

        dangerTiles = set()
        for dangerPath in dangerPaths:
            if dangerPath is not None:
                dangerTiles.update(SearchUtils.where(dangerPath.tileList, lambda t: bot._map.is_tile_enemy(t) and t.army > 2))

        return dangerTiles

    @staticmethod
    def get_danger_paths(bot, move_half=False) -> typing.List[Path]:
        thresh = 3
        if move_half:
            thresh = bot.general.army - bot.general.army // 2 + 2

        dangerPaths = []
        if bot.targetPlayer != -1:
            dangerPath = SearchUtils.dest_breadth_first_target(bot._map, bot.general.movable, targetArmy=thresh, maxTime=0.1, maxDepth=2, searchingPlayer=bot.targetPlayer, ignoreGoalArmy=False)
            if dangerPath is not None:
                dangerPaths.append(dangerPath)
                altSet = dangerPath.tileSet.copy()

                altPath = SearchUtils.dest_breadth_first_target(bot._map, bot.general.movable, negativeTiles=altSet, targetArmy=thresh, maxTime=0.1, maxDepth=2, searchingPlayer=bot.targetPlayer, ignoreGoalArmy=False)
                if altPath is not None:
                    dangerPaths.append(altPath)
                    altSet.discard(altPath.start.tile)

                altSet.discard(dangerPath.start.tile)

                altPath = SearchUtils.dest_breadth_first_target(bot._map, bot.general.movable, negativeTiles=altSet, targetArmy=thresh, maxTime=0.1, maxDepth=2, searchingPlayer=bot.targetPlayer, ignoreGoalArmy=False)
                if altPath is not None and str(altPath) != str(dangerPath):
                    dangerPaths.append(altPath)

        for mv in bot.general.movable:
            if bot._map.is_tile_enemy(mv) and mv.army >= thresh:
                path = Path()
                path.add_next(mv)
                path.add_next(bot.general)
                dangerPaths.append(path)

        for dangerPath in dangerPaths:
            bot.info(f'DBG: DangerPath {dangerPath}')

        return dangerPaths

    @staticmethod
    def determine_should_defend_ally(bot) -> bool:
        threat = bot.dangerAnalyzer.fastestAllyThreat

        if bot.teammate_communicator is not None:
            if bot.teammate_communicator.is_defense_lead:
                return True

        allowComms = threat.path.start.tile.visible

        teammateSelfSavePathShort = bot.get_best_defense(
            threat.path.tail.tile,
            threat.turns - 3,
            threat.path.tileList)
        if teammateSelfSavePathShort is not None:
            logbook.info(
                f"  threatVal {threat.threatValue}, teammateSelfSavePathShort {str(teammateSelfSavePathShort)}")
            if threat.threatValue < teammateSelfSavePathShort.value:
                if allowComms:
                    bot.send_teammate_communication(
                        f"|  Need {threat.threatValue} @ you in {threat.turns} moves. Expecting you to block by yourself with pinged tile.",
                        threat.path.start.tile,
                        detectionKey='allyDefense',
                        cooldown=10)
                    bot.send_teammate_tile_ping(threat.path.tail.tile, cooldown=10)
                    bot.send_teammate_tile_ping(teammateSelfSavePathShort.start.next.tile, cooldown=10)
                return False

        teammateSelfSavePath = bot.get_best_defense(
            threat.path.tail.tile,
            threat.turns - 1,
            threat.path.tileList)
        if teammateSelfSavePath is not None:
            logbook.info(
                f"  threatVal {threat.threatValue}, teammateSelfSavePath {str(teammateSelfSavePath)}")
            if threat.threatValue < teammateSelfSavePath.value:
                if allowComms:
                    bot.send_teammate_communication(
                        f"-- Need {threat.threatValue} @ you in {threat.turns} moves. You may barely manage. Protecting you just in case.",
                        detectionKey='allyDefenseBarely',
                        cooldown=10)
                    bot.send_teammate_tile_ping(threat.path.tail.tile, cooldown=10)
                    bot.send_teammate_tile_ping(teammateSelfSavePath.start.next.tile, cooldown=10)
                return True
            else:
                if allowComms:
                    bot.send_teammate_communication(
                        f"---Need {threat.threatValue} @ you in {threat.turns} moves. You may be unable to save yourself by {threat.threatValue - teammateSelfSavePath.value} army, trying to help.",
                        threat.path.start.tile,
                        detectionKey='allyDefense',
                        cooldown=10)
                    if teammateSelfSavePath.start.tile.lastMovedTurn < bot._map.turn - 1:
                        bot.send_teammate_tile_ping(teammateSelfSavePath.start.tile, cooldown=10, cooldownKey='allyDefensePing')
                return True

        if allowComms:
            bot.send_teammate_communication(
                f"---Need {threat.threatValue} @ you in {threat.turns} moves. You have no defense, trying to defend you.",
                threat.path.start.next.tile,
                detectionKey='allyDefense',
                cooldown=10)
            bot.send_teammate_tile_ping(threat.path.tail.tile, cooldown=10, cooldownKey='allyDefensePing')
        return True

    @staticmethod
    def get_approximate_fog_risk_deficit(bot) -> int:
        cycleTurnsLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)

        pathWorth = bot.get_player_army_amount_on_path(bot.target_player_gather_path, bot.general.player)
        pushRiskTurns = cycleTurnsLeft - bot.target_player_gather_path.length
        pushRiskTurns = 0

        if bot.targetPlayer != -1:
            fogRisk = bot.opponent_tracker.get_approximate_fog_army_risk(bot.targetPlayer, inTurns=pushRiskTurns)
            deficit = fogRisk - pathWorth - pushRiskTurns // 2
            bot.viewInfo.add_stats_line(f'get_approximate_fog_risk_deficit {deficit} based on fogRisk {fogRisk} (our path {pathWorth}) in turns {pushRiskTurns}')
            return deficit

        return 0

    @staticmethod
    def should_abandon_king_defense(bot) -> bool:
        return bot._map.remainingPlayers == 2 and not bot.opponent_tracker.winning_on_economy(byRatio=bot.behavior_losing_on_economy_skip_defense_threshold)

    @staticmethod
    def should_defend_economy(bot, defenseTiles: typing.Set[Tile]):
        if bot._map.remainingPlayers > 2:
            return False
        if bot.targetPlayer == -1:
            return False

        if bot.targetPlayerObj.last_seen_move_turn < bot._map.turn - 100:
            bot.viewInfo.add_info_line(f'ignoring econ defense against afk player')
            return False

        genPlayer = bot._map.players[bot.general.player]

        wasDefending = bot.defend_economy

        bot.defend_economy = False
        if bot.check_should_defend_economy_based_on_large_tiles():
            bot.defend_economy = True
            return True

        if bot.check_should_defend_economy_based_on_cycle_behavior(defenseCriticalTileSet=defenseTiles):
            bot.viewInfo.add_info_line(f'DEF ECON BASED ON CYCLE BEHAVIOR')
            bot.defend_economy = True
            if not wasDefending:
                bot.currently_forcing_out_of_play_gathers = True
                bot.timings = bot.get_timings()
            return True

        if bot.timings.get_turn_in_cycle(bot._map.turn) < bot.timings.launchTiming:
            if (
                    bot.army_out_of_play
                    and not bot.opponent_tracker.winning_on_army(byRatio=1.6)
                    and bot.opponent_tracker.winning_on_economy(byRatio=1.1, offset=0)
                    and genPlayer.tileCount < 120
                    and not bot.flanking
            ):
                requirementRatio = 0.8
                if wasDefending:
                    requirementRatio = 0.9

                required = bot.fog_risk_amount * requirementRatio

                totalDefensive = 0
                totalDefensiveHeld = 0
                defenseTreeBackToFront = sorted(bot.defensive_spanning_tree, key=lambda t: bot.territories.territoryTeamDistances[bot.targetPlayerObj.team].raw[t.tile_index], reverse=True)
                for tile in defenseTreeBackToFront:
                    if totalDefensive < required:
                        defenseTiles.add(tile)
                        bot.viewInfo.add_targeted_tile(tile, TargetStyle.WHITE)
                        totalDefensiveHeld += tile.army

                    totalDefensive += tile.army

                if totalDefensive > required:
                    bot.viewInfo.add_info_line(f'BYP DEF W HELD TILES {totalDefensiveHeld} ({totalDefensive} total) vs {required:.0f}')
                    return False

                bot.defend_economy = True

                if not bot.currently_forcing_out_of_play_gathers:
                    bot.currently_forcing_out_of_play_gathers = True
                    bot.timings = bot.get_timings()

                return True
            else:
                bot.currently_forcing_out_of_play_gathers = False

        winningText = "first 100 still"
        if bot._map.turn >= 100:
            econRatio = 1.16
            armyRatio = 1.42
            enemyCatchUpOffset = -15

            winningEcon = bot.opponent_tracker.winning_on_economy(econRatio, cityValue=20, againstPlayer=bot.targetPlayer, offset=enemyCatchUpOffset)
            winningArmy = bot.opponent_tracker.winning_on_army(armyRatio)
            pathLen = 20
            if bot.shortest_path_to_target_player is not None:
                pathLen = bot.shortest_path_to_target_player.length

            playerArmyNearGeneral = bot.sum_friendly_army_near_or_on_tiles(bot.shortest_path_to_target_player.tileList, distance=pathLen // 4 + 1)
            armyThresh = int(bot.targetPlayerObj.standingArmy ** 0.93)
            hasEnoughArmyNearGeneral = playerArmyNearGeneral > armyThresh

            bot.defend_economy = winningEcon and (not winningArmy or not hasEnoughArmyNearGeneral)
            if bot.defend_economy:
                if not hasEnoughArmyNearGeneral and winningArmy:
                    bot.viewInfo.add_info_line("FORCING MAX GATHER TIMINGS BECAUSE NOT ENOUGH ARMY NEAR GEN AND DEFENDING ECONOMY")
                    bot.timings.split = bot.timings.cycleTurns
                logbook.info(
                    f"\n\nDEF ECONOMY! winning_on_econ({econRatio}) {str(winningEcon)[0]}, on_army({armyRatio}) {str(winningArmy)[0]}, enough_near_gen({playerArmyNearGeneral}/{armyThresh}) {str(hasEnoughArmyNearGeneral)[0]}")
                winningText = f"! woe{econRatio} {str(winningEcon)[0]}, woa{armyRatio} {str(winningArmy)[0]}, sa{playerArmyNearGeneral}/{armyThresh} {str(hasEnoughArmyNearGeneral)[0]}"
            else:
                logbook.info(
                    f"\n\nNOT DEFENDING ECONOMY? winning_on_econ({econRatio}) {str(winningEcon)[0]}, on_army({armyRatio}) {str(winningArmy)[0]}, enough_near_gen({playerArmyNearGeneral}/{armyThresh}) {str(hasEnoughArmyNearGeneral)[0]}")
                winningText = f"  woe{econRatio} {str(winningEcon)[0]}, woa{armyRatio} {str(winningArmy)[0]}, sa{playerArmyNearGeneral}/{armyThresh} {str(hasEnoughArmyNearGeneral)[0]}"

        bot.viewInfo.addlTimingsLineText = winningText

        return bot.defend_economy

    @staticmethod
    def check_should_defend_economy_based_on_cycle_behavior(bot, defenseCriticalTileSet: typing.Set[Tile]) -> bool:
        bot.likely_kill_push = False

        if bot.is_ffa_situation():
            return False

        halfDist = bot.shortest_path_to_target_player.length - bot.shortest_path_to_target_player.length // 2

        oppArmy = bot.opponent_tracker.get_approximate_fog_army_risk(bot.targetPlayer)
        enGathered = 0
        enData = bot.opponent_tracker.get_current_cycle_stats_by_player(bot.targetPlayer)
        if enData:
            enGathered = enData.approximate_army_gathered_this_cycle
        if oppArmy < enGathered:
            bot.viewInfo.add_info_line(f'Skipping defense play because fogRisk {oppArmy} < en gathered {enGathered}.')
            return False

        threatPath = bot.target_player_gather_path

        if bot.enemy_attack_path is not None:
            enPath = bot.enemy_attack_path.get_subsegment(halfDist + 2, end=True)

            threatPath = bot.enemy_attack_path
            enemyAttackPathVal = sum([t.army - 1 for t in enPath.tileList if bot._map.is_tile_on_team_with(t, bot.targetPlayer) and (t.visible or t.army < 8)])

            enemyAttackPathEnOrFogTiles = sum([1.25 for t in enPath.tileList if (bot._map.is_tile_on_team_with(t, bot.targetPlayer) or not t.visible) and t.army > 2])
            enemyAttackPathEnOrFogTiles += sum([0.95 for t in enPath.tileList if (bot._map.is_tile_on_team_with(t, bot.targetPlayer) or not t.visible) and t.army == 2])
            enemyAttackPathEnOrFogTiles += sum([0.55 for t in enPath.tileList if (bot._map.is_tile_on_team_with(t, bot.targetPlayer) or not t.visible) and t.army <= 1])

            if enemyAttackPathVal > 5:
                bot.viewInfo.add_info_line(f'dangerPath with army {enemyAttackPathVal}, increasing oppArmy risk by that.')
                oppArmy += enemyAttackPathVal

            if enemyAttackPathEnOrFogTiles > halfDist // 2:
                bot.viewInfo.add_info_line(f'likely_kill_push: danger enTileCount weighted {enemyAttackPathEnOrFogTiles:.1f}>halfDist/2 {halfDist//2}, triggering defensive play.')
                bot.likely_kill_push = True

        sketchDist = bot.board_analysis.within_flank_danger_play_area_threshold
        if bot.sketchiest_potential_inbound_flank_path is not None:
            sketchDist = bot._map.get_distance_between(bot.general, bot.sketchiest_potential_inbound_flank_path.tail.tile)

        if not bot.opponent_tracker.winning_on_economy(byRatio=1.08, offset=0 - bot.shortest_path_to_target_player.length) and not bot.likely_kill_push:
            return False

        if bot.timings.get_turns_left_in_cycle(bot._map.turn) <= max(halfDist, sketchDist):
            if bot.likely_kill_push:
                bot.viewInfo.add_info_line(f'bypassing likely_kill_push defense due to near end-of-round')
            return False

        cycleDifferential = bot.opponent_tracker.check_gather_move_differential(bot.general.player, bot.targetPlayer)

        playerArmy = 8
        for tile in bot.armyTracker.armies:
            if tile.player == bot.general.player and tile.army > playerArmy:
                playerArmy = tile.army - 1

        gathPathSum = 0
        for tile in threatPath.tileList:
            if bot._map.is_tile_friendly(tile):
                gathPathSum += tile.army - 1

        playerArmy = max(playerArmy, gathPathSum)

        if oppArmy - gathPathSum > 0 and not bot.timings.in_expand_split(bot._map.turn):
            for tile in threatPath.tileList:
                if bot._map.is_tile_friendly(tile):
                    defenseCriticalTileSet.add(tile)
                    bot.viewInfo.add_targeted_tile(tile, TargetStyle.YELLOW)

            bot.viewInfo.add_info_line(f'updated defenseCriticals with gather path due to oppArmy {oppArmy} - gathPathSum {gathPathSum} > 0: {str(defenseCriticalTileSet)}')

        if oppArmy + 10 - halfDist <= playerArmy:
            if oppArmy + 10 - halfDist >= playerArmy - 40 and bot.likely_kill_push:
                bot.block_neutral_captures("likely_kill_push says capping a city would put us under safe army for the push")
            if cycleDifferential < -halfDist:
                bot.viewInfo.add_info_line(f'OT oppArmy {oppArmy} vs {playerArmy} - gathMoveDiff {cycleDifferential}, but gathered enough that we dont care?')
            return False

        if cycleDifferential < -halfDist and oppArmy >= playerArmy:
            bot.viewInfo.add_info_line(f'DEFENDING! OT gathCyc oppArmy {oppArmy} vs {playerArmy} - gathMoveDiff {cycleDifferential}')
            bot.defend_economy = True
            return True

        turnsRemaining = bot.timings.get_turns_left_in_cycle(bot._map.turn)
        minimallyWinningOnEcon = bot.opponent_tracker.winning_on_economy(byRatio=1.02, offset=0 - bot.shortest_path_to_target_player.length // 2)
        if not minimallyWinningOnEcon and oppArmy - threatPath.length < playerArmy * 1.25 and turnsRemaining < 13:
            return False

        if oppArmy >= (playerArmy + 10) * 1.1 and cycleDifferential < 5 and minimallyWinningOnEcon:
            bot.viewInfo.add_info_line(f'DEFENDING! OT army oppArmy {oppArmy} vs {playerArmy} - gathMoveDiff {cycleDifferential}')
            return True

        return False

    @staticmethod
    def get_threat_killer_move(bot, threat, searchTurns, negativeTiles):
        killTiles = [threat.path.start.tile]
        if threat.path.start.next:
            killTiles.insert(0, threat.path.start.next.tile)

        threatTile = threat.path.start.tile

        if threat.turns > bot.shortest_path_to_target_player.length // 2 and bot.board_analysis.intergeneral_analysis.bMap[threatTile] < threat.turns > bot.shortest_path_to_target_player.length // 2:
            return None

        armyAmount = threat.threatValue + 1
        saveTile = None
        largestTile = None
        source = None
        for threatSource in killTiles:
            for tile in threatSource.movable:
                if tile.player == bot._map.player_index and tile not in threat.path.tileSet and tile not in bot.expansion_plan.blocking_tiles:
                    if tile.army > 1 and (largestTile is None or tile.army > largestTile.army):
                        largestTile = tile
                        source = threatSource
        threatModifier = 3
        if (bot._map.turn - 1) in bot.history.attempted_threat_kills:
            logbook.info("We attempted a threatKill last turn, using 1 instead of 3 as threatKill modifier.")
            threatModifier = 1

        if largestTile is not None:
            if threat.threatValue - largestTile.army + threatModifier < 0:
                logbook.info(f"reeeeeeeeeeeeeeeee\nFUCK YES KILLING THREAT TILE {largestTile.x},{largestTile.y}")
                saveTile = largestTile
            else:
                negativeTilesIncludingThreat = set()
                negativeTilesIncludingThreat.add(largestTile)
                dict = {}
                dict[bot.general] = (0, threat.threatValue, 0)
                for tile in negativeTiles:
                    negativeTilesIncludingThreat.add(tile)
                for tile in threat.path.tileSet:
                    negativeTilesIncludingThreat.add(tile)
                if threat.saveTile is not None:
                    dict[threat.saveTile] = (0, threat.threatValue, -0.5)
                    logbook.info(f"(killthreat) dict[threat.saveTile] = (0, {threat.saveTile.army})  -- threat.saveTile {threat.saveTile.x},{threat.saveTile.y}")
                savePathSearchModifier = 2
                if largestTile in threat.path.start.tile.movable:
                    logbook.info("largestTile was adjacent to the real threat tile, so savepath needs to be 1 turn shorter for this to be safe")
                    savePathSearchModifier = 3

        if saveTile is not None:
            bot.history.attempted_threat_kills.add(bot._map.turn)
            return Move(saveTile, source)
        return None

    @staticmethod
    def calculate_general_danger(bot):
        depth = bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation)
        if depth < 9:
            depth = 9
        if bot.is_2v2_teammate_still_alive():
            depth += 5

        bot.oldThreat = bot.dangerAnalyzer.fastestThreat
        bot.oldAllyThreat = bot.dangerAnalyzer.fastestAllyThreat

        cities = []
        for player in bot._map.players:
            if player.team == bot._map.team_ids_by_player_index[bot.general.player] and not player.dead:
                cities.extend(player.cities)

        bot.dangerAnalyzer.analyze(cities, depth, bot.armyTracker.armies)

        if bot.dangerAnalyzer.fastestThreat:
            bot.viewInfo.add_stats_line(f'Threat@{str(bot.dangerAnalyzer.fastestThreat.path.tail.tile)}: {str(bot.dangerAnalyzer.fastestThreat.path)}')
            if bot.dangerAnalyzer.fastestThreat.saveTile is not None:
                bot.viewInfo.add_stats_line(f'SaveTile@{str(bot.dangerAnalyzer.fastestThreat.saveTile)}')

        if bot.dangerAnalyzer.fastestCityThreat:
            bot.viewInfo.add_stats_line(f'CThreat@{str(bot.dangerAnalyzer.fastestCityThreat.path.tail.tile)}: {str(bot.dangerAnalyzer.fastestCityThreat.path)}')
        if bot.dangerAnalyzer.fastestVisionThreat:
            bot.viewInfo.add_stats_line(f'VThreat@{str(bot.dangerAnalyzer.fastestVisionThreat.path.tail.tile)}: {str(bot.dangerAnalyzer.fastestVisionThreat.path)}')
        if bot.dangerAnalyzer.fastestAllyThreat:
            bot.viewInfo.add_stats_line(f'AThreat@{str(bot.dangerAnalyzer.fastestAllyThreat.path.tail.tile)}: {str(bot.dangerAnalyzer.fastestAllyThreat.path)}')
        if bot.dangerAnalyzer.fastestPotentialThreat:
            bot.viewInfo.add_stats_line(f'PotThreat@{str(bot.dangerAnalyzer.fastestPotentialThreat.path.tail.tile)}: {str(bot.dangerAnalyzer.fastestPotentialThreat.path)}')

        if bot.should_abandon_king_defense():
            bot.viewInfo.add_stats_line(f'skipping defense because losing on econ')

    @staticmethod
    def _get_flank_defense_leafmove(bot, flankPath: Path, coreNegs: typing.Set[Tile]) -> Move | None:
        bestWeighted = 3
        bestMove = None
        for leafMove in bot.captureLeafMoves:
            if leafMove.dest.isSwamp:
                continue
            if leafMove.source in coreNegs:
                continue

            dist = bot._map.get_distance_between(flankPath.tail.tile, leafMove.dest)
            revealed = 0
            for t in leafMove.dest.adjacents:
                if t in bot.board_analysis.flankable_fog_area_matrix:
                    revealed += 1

            weighted = dist + revealed
            if dist < 2 or weighted < bestWeighted:
                continue

            if leafMove.dest in flankPath.adjacentSet:
                bestMove = leafMove
                bestWeighted = weighted

        return bestMove

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
            cutoff = bot.get_median_tile_value(85) + 2
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

    @staticmethod
    def _get_flank_vision_defense_move_internal(bot, flankThreatPath: Path, negativeTiles: typing.Set[Tile], atDist: int) -> Move | None:
        included = set()
        for tile in flankThreatPath.tileList[:(flankThreatPath.length * 5) // 6]:
            if tile in bot.board_analysis.flank_danger_play_area_matrix and not tile.visible and not tile.isSwamp:
                included.add(tile)

        for t in included:
            bot.viewInfo.add_targeted_tile(t, targetStyle=TargetStyle.GOLD, radiusReduction=11)

        flankThreatTiles = set(flankThreatPath.tileList[flankThreatPath.length // 2:])

        SearchUtils.breadth_first_foreach(bot._map, bot.target_player_gather_path.adjacentSet, maxDepth=2, foreachFunc=lambda t: flankThreatTiles.discard(t), noLog=True)
        if len(flankThreatTiles) < flankThreatPath.length // 5 + 1:
            return None

        capture_first_value_func = bot.get_capture_first_tree_move_prio_func()

        move = None
        offset = 0
        maxOffs = bot.target_player_gather_path.length // 4

        while move is None and offset < maxOffs:
            gathTurns = offset + (50 - bot._map.turn) % 4
            move, valGathered, gatherTurns, gatherNodes = bot.get_gather_to_target_tiles(
                [t for t in included],
                maxTime=0.002,
                gatherTurns=gathTurns,
                maximizeArmyGatheredPerTurn=True,
                targetArmy=0,
                leafMoveSelectionValueFunc=capture_first_value_func,
                useTrueValueGathered=True,
                includeGatherTreeNodesThatGatherNegative=False,
                negativeSet=negativeTiles)

            caps = SearchUtils.Counter(0)

            if gatherNodes is not None and len(gatherNodes) > 0:
                def foreachFunc(n: GatherTreeNode):
                    if len(n.children) > 0:
                        caps.value += (0 if bot._map.is_tile_friendly(n.tile) else 1)

                GatherTreeNode.foreach_tree_node(gatherNodes, foreachFunc)

                playerArmyBaseline = int(bot.player.standingArmy / bot.player.tileCount)
                wasteWeight = gatherTurns - caps.value

                if wasteWeight <= 0:
                    sumPrunedTurns, sumPruned, gatherNodes = Gather.prune_mst_to_army_with_values(
                        gatherNodes,
                        1,
                        bot.general.player,
                        MapBase.get_teams_array(bot._map),
                        bot._map.turn,
                        viewInfo=bot.viewInfo,
                        noLog=True)
                    bot.viewInfo.add_info_line(f'Flank Gath valGathered {sumPruned}({valGathered}) / (gatherTurns {sumPrunedTurns}({gatherTurns}) - caps {caps.value}) vs {playerArmyBaseline}')
                    path = Path()
                    n = SearchUtils.where(gatherNodes, lambda n: n.gatherTurns > 0)[0]
                    while True:
                        path.add_start(n.tile)
                        if len(n.children) == 0:
                            break
                        n = n.children[0]

                    if path.length > 0:
                        bot.curPath = path

                elif 3 * valGathered / wasteWeight < playerArmyBaseline:
                    bot.viewInfo.add_info_line(f'increasing flank def due to valGathered {valGathered} / (gatherTurns {gatherTurns} - caps {caps.value}) vs {playerArmyBaseline}')
                    move = None

            offset += 2

        if move is not None:
            return move

        return None

    @staticmethod
    def find_flank_defense_move(bot, defenseCriticalTileSet: typing.Set[Tile], highPriority: bool = False) -> Move | None:
        checkPath = bot.sketchiest_potential_inbound_flank_path

        if bot.enemy_attack_path is not None and bot.likely_kill_push:
            bot.info(f'~~risk threat - replacing flank with risk threat BC likely_kill_push')
            checkPath = bot.enemy_attack_path.get_subsegment_excluding_trailing_visible()
        elif bot.is_ffa_situation():
            return None

        checkFlank = checkPath is not None and (
                checkPath.tail.tile in bot.board_analysis.flank_danger_play_area_matrix
                or checkPath.tail.tile in bot.board_analysis.core_play_area_matrix
        )

        coreNegs = defenseCriticalTileSet.copy()
        coreNegs.update(bot.win_condition_analyzer.defend_cities)
        coreNegs.update(bot.win_condition_analyzer.contestable_cities)

        if highPriority and checkPath:
            winningMassivelyOnArmy = bot.opponent_tracker.winning_on_army(byRatio=1.4) and bot.opponent_tracker.winning_on_economy(byRatio=1.15)
            winningMassivelyOnEcon = bot.opponent_tracker.winning_on_army(byRatio=1.1) and bot.opponent_tracker.winning_on_economy(byRatio=1.4)
            winningInTheMiddle = bot.opponent_tracker.winning_on_army(byRatio=1.25) and bot.opponent_tracker.winning_on_economy(byRatio=1.05, offset=-25)
            winningByEnoughToBeSuperCareful = winningMassivelyOnArmy or winningMassivelyOnEcon or winningInTheMiddle

            flankIsCloserThanThreeFifths = bot.distance_from_general(checkPath.tail.tile) < 3 * bot.shortest_path_to_target_player.length // 5
            if winningByEnoughToBeSuperCareful and flankIsCloserThanThreeFifths:
                turns = 3 + (bot.timings.get_turns_left_in_cycle(bot._map.turn) + 1) % 4
                with bot.perf_timer.begin_move_event(f'superCareful flank gath {turns}t'):
                    startTiles = checkPath.convert_to_dist_dict(offset=0 - checkPath.length)
                    for t in list(startTiles.keys()):
                        if t.isSwamp or SearchUtils.any_where(t.movable, lambda m: m.isSwamp):
                            startTiles.pop(t)
                    move = None
                    if len(startTiles) > 0:
                        move, valGathered, turnsUsed, nodes = bot.get_gather_to_target_tiles(
                            startTiles,
                            maxTime=0.002,
                            gatherTurns=turns,
                            negativeSet=defenseCriticalTileSet,
                            targetArmy=1,
                            useTrueValueGathered=True,
                            includeGatherTreeNodesThatGatherNegative=False,
                            maximizeArmyGatheredPerTurn=True,
                            priorityMatrix=bot.get_expansion_weight_matrix(mult=10))

                    if move:
                        forcedHalf = False
                        if 4 < valGathered <= move.source.army // 2 and not bot.is_move_towards_enemy(move):
                            move.move_half = True
                            forcedHalf = True
                        bot.info(f'superCareful flank gath for {turns}t: {move} ({valGathered} in {turnsUsed}t). Half {forcedHalf}')
                        return move

                leafMove = bot._get_vision_expanding_available_move(coreNegs, checkPath)
                if leafMove is not None:
                    return leafMove

            return None

        if BotStateQueries.is_still_ffa_and_non_dominant(bot):
            return None

        leafMove = bot._get_vision_expanding_available_move(coreNegs, checkPath)
        if leafMove is not None:
            return leafMove

        if not checkFlank:
            return None

        if checkFlank:
            leafMove = bot._get_flank_defense_leafmove(checkPath, coreNegs)
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
        flankDefMove = bot._get_flank_vision_defense_move_internal(
            checkPath,
            negs,
            atDist=bot.board_analysis.within_flank_danger_play_area_threshold)
        if flankDefMove is not None:
            bot.info(f'proactive flank vision defense {str(flankDefMove)}')
            return flankDefMove

        flankDefMove = bot._get_flank_vision_defense_move_internal(
            checkPath,
            coreNegs,
            atDist=bot.board_analysis.within_flank_danger_play_area_threshold)
        if flankDefMove is not None:
            bot.info(f'No exp negs proactive flank vision defense {str(flankDefMove)}')
            return flankDefMove

        return None

    @staticmethod
    def check_should_defend_economy_based_on_large_tiles(bot) -> bool:
        largeEnemyTiles = bot.find_large_tiles_near(
            [t for t in bot.board_analysis.intergeneral_analysis.shortestPathWay.tiles],
            distance=4,
            forPlayer=bot.targetPlayer,
            limit=1,
            minArmy=30,
            allowGeneral=False
        )

        largeFriendlyTiles = bot.find_large_tiles_near(
            [t for t in bot.board_analysis.intergeneral_analysis.shortestPathWay.tiles],
            distance=5,
            forPlayer=bot.general.player,
            limit=1,
            minArmy=1,
            allowGeneral=False
        )

        largeFriendlyArmy = 0
        if len(largeFriendlyTiles) > 0:
            largeFriendlyArmy = largeFriendlyTiles[0].army

        bot.is_blocking_neutral_city_captures = False

        if len(largeEnemyTiles) > 0:
            largeEnTile = largeEnemyTiles[0]
            me = bot._map.players[bot.general.player]
            dist = bot.distance_from_general(largeEnTile)
            thresh = 2 * me.standingArmy // 3 + dist
            if largeEnTile.army > largeFriendlyArmy and largeEnTile.army > thresh and dist < 2 * bot.board_analysis.inter_general_distance // 3 and not largeEnTile.isGeneral:
                bot.defend_economy = True
                bot.viewInfo.add_info_line(f'marking defending economy due to large enemy tile {str(largeEnTile)} (thresh {thresh})')
                bot.force_city_take = False
                if largeEnTile.army > largeFriendlyArmy + 35 and largeEnTile.army > me.standingArmy // 2 - 35 and not bot._map.is_2v2:
                    bot.is_blocking_neutral_city_captures = True

            if bot.curPath and bot.curPath.tail is not None and bot.curPath.tail.tile.isCity and bot.curPath.tail.tile.isNeutral and bot.is_blocking_neutral_city_captures:
                targetNeutCity = bot.curPath.tail.tile
                if bot.is_blocking_neutral_city_captures:
                    bot.info(
                        f'forcibly stopped taking neutral city {str(targetNeutCity)} due to unsafe tile {str(largeEnTile)}')
                    bot.curPath = None
                    bot.force_city_take = False

            return False

            if bot.timings.get_turns_left_in_cycle(bot._map.turn) < 5:
                return False

            if bot.defend_economy:
                return True

        return False

    @staticmethod
    def get_best_defense(bot, defendingTile: Tile, turns: int, negativeTileList: typing.List[Tile]) -> Path | None:
        searchingPlayer = defendingTile.player
        logbook.info(f"Trying to get_best_defense. Turns {turns}. Searching player {searchingPlayer}")
        negativeTiles = set()

        for negTile in negativeTileList:
            negativeTiles.add(negTile)

        startTiles = [defendingTile]

        def default_value_func_max_army(currentTile, priorityObject):
            (dist, negArmySum, xSum, ySum) = priorityObject
            return 0 - negArmySum, 0 - dist

        valueFunc = default_value_func_max_army

        def default_priority_func(nextTile, currentPriorityObject):
            (dist, negArmySum, xSum, ySum) = currentPriorityObject
            negArmySum += 1
            if searchingPlayer == nextTile.player:
                negArmySum -= nextTile.army
            else:
                negArmySum += nextTile.army

            return dist + 1, negArmySum, xSum + nextTile.x, ySum + nextTile.y

        priorityFunc = default_priority_func

        def default_base_case_func(t, startingDist):
            return 0, 0, t.x, t.y

        baseCaseFunc = default_base_case_func

        startTilesDict = {}
        for tile in startTiles:
            startTilesDict[tile] = (baseCaseFunc(tile, 0), 0)

        for tile in startTilesDict.keys():
            (startPriorityObject, distance) = startTilesDict[tile]
            logbook.info(f"   Including tile {tile} in startTiles at distance {distance}")

        valuePerTurnPath = SearchUtils.breadth_first_dynamic_max(
            bot._map,
            startTilesDict,
            valueFunc,
            0.1,
            turns,
            turns,
            noNeutralCities=True,
            negativeTiles=negativeTiles,
            searchingPlayer=searchingPlayer,
            priorityFunc=priorityFunc,
            ignoreStartTile=True,
            preferNeutral=False,
            noLog=True)

        if valuePerTurnPath is not None:
            if DebugHelper.IS_DEBUGGING:
                logbook.info(f"Best defense: {valuePerTurnPath.toString()}")
            savePath = valuePerTurnPath.get_reversed()
            negs = set(negativeTileList)
            negs.add(defendingTile)
            savePath.calculate_value(forPlayer=defendingTile.player, teams=bot._map.team_ids_by_player_index, negativeTiles=negs)

            if DebugHelper.IS_DEBUGGING:
                bot.viewInfo.color_path(PathColorer(savePath, 255, 255, 255, 255, 10, 150))
            return savePath

        if DebugHelper.IS_DEBUGGING:
            logbook.info("Best defense: NONE")
        return None

    @staticmethod
    def set_defensive_blocks_against(bot, threat):
        for gatherTreeNode in bot.best_defense_leaves:
            defensiveTile = gatherTreeNode.tile
            if defensiveTile.army <= 2 and gatherTreeNode.toTile.army > defensiveTile.army:
                defensiveTile = gatherTreeNode.toTile
            block = bot.blocking_tile_info.get(defensiveTile, None)
            amountNecessary = max(0, threat.threatValue - defensiveTile.army)
            if not block:
                block = ThreatBlockInfo(
                    defensiveTile,
                    amount_needed_to_block=min(defensiveTile.army, amountNecessary),
                )
                bot.blocking_tile_info[defensiveTile] = block

            block.amount_needed_to_block = min(defensiveTile.army, max(block.amount_needed_to_block, amountNecessary))
            defDist = threat.armyAnalysis.interceptDistances.raw[defensiveTile.tile_index]
            if defDist is None:
                if threat.armyAnalysis.pathWayLookupMatrix.raw[defensiveTile.tile_index] is not None:
                    defDist = threat.armyAnalysis.pathWayLookupMatrix.raw[defensiveTile.tile_index].distance
                else:
                    defDist = 100
            for t in defensiveTile.movable:
                tDist = threat.armyAnalysis.interceptDistances.raw[t.tile_index]
                if tDist is None:
                    if threat.armyAnalysis.pathWayLookupMatrix.raw[t.tile_index] is not None:
                        tDist = threat.armyAnalysis.pathWayLookupMatrix.raw[t.tile_index].distance
                    else:
                        tDist = 100
                if defDist < tDist:
                    block.add_blocked_destination(t)
            bot.info(f'blocking {defensiveTile} from moving to {block.blocked_destinations}')
