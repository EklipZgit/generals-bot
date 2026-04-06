import time
import typing

import BotModules as BM
import logbook

import Gather
import SearchUtils
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotRepetition import BotRepetition

from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotRendering import BotRendering
from ArmyAnalyzer import ArmyAnalyzer
from DangerAnalyzer import ThreatObj, ThreatType
from Gather import GatherTreeNode
from Path import Path, MoveListPath
from ViewInfo import TargetStyle
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix, TileSet
from base.client.map import MapBase, Tile
from Models.Move import Move

GATHER_SWITCH_POINT = 150

class BotGatherOps:
    @staticmethod
    def get_number_of_captures_in_gather_tree(bot, gatherNodes: typing.List[GatherTreeNode], asPlayer: int = -2) -> int:
        if asPlayer == -2:
            asPlayer = bot._map.player_index

        if gatherNodes is None or len(gatherNodes) == 0:
            return 0

        sumCaps = SearchUtils.Counter(0)

        def c(n: GatherTreeNode):
            if not bot._map.is_tile_on_team_with(n.tile, asPlayer) and len(n.children) > 0:
                sumCaps.value += 1

        GatherTreeNode.foreach_tree_node(gatherNodes, forEachFunc=c)

        return sumCaps.value

    @staticmethod
    def convert_gather_to_move_list_path(bot, gatherNodes, turnsUsed, value, moveOrderPriorityMinFunc) -> MoveListPath:
        gcp = Gather.GatherCapturePlan.build_from_root_nodes(bot._map, gatherNodes, negativeTiles=set(), searchingPlayer=bot._map.player_index, onlyCalculateFriendlyArmy=False, priorityMatrix=None, viewInfo=bot.viewInfo)
        moveListThing = []
        move = gcp.pop_first_move()
        while move:
            moveListThing.append(move)
            move = gcp.pop_first_move()

        bot.info(f'gath {len(gatherNodes)} root, moves {" - ".join([str(m) for m in moveListThing])}')
        return MoveListPath(moveListThing)

    @staticmethod
    def try_find_gather_move(
            bot,
            threat: ThreatObj | None,
            defenseCriticalTileSet: typing.Set[Tile],
            leafMoves: typing.List[Move],
            needToKillTiles: typing.List[Tile],
    ) -> Move | None:
        tryGather = True
        player = bot._map.players[bot.general.player]
        enemyGather = False
        if (
                BM.BotDefense.BotDefense.get_approximate_fog_risk_deficit(bot, ) < 10
                and not bot._map.remainingPlayers > 2
                and not bot.opponent_tracker.winning_on_economy(byRatio=1.1, cityValue=0)
        ):
            logbook.info("Forced enemyGather to true due to NOT winning_on_economy(by tiles only) and winning_on_army")
            enemyGather = True

        if BotStateQueries.is_all_in(bot):
            move = BM.BotCombatOps.BotCombatOps.try_find_flank_all_in(bot, bot.timings.get_turns_left_in_cycle(bot._map.turn))
            if move is not None:
                bot.info(f'flank all in {move}')
                return move

            return None

        neutralGather = False
        player = bot._map.players[bot.general.player]

        tileDeficitThreshold = bot._map.players[bot.targetPlayer].tileCount * 1.05
        if bot.makingUpTileDeficit:
            tileDeficitThreshold = bot._map.players[bot.targetPlayer].tileCount * 1.15 + 8

        if (
                not bot.defend_economy
                and bot.distance_from_general(bot.targetPlayerExpectedGeneralLocation) > 2
                and player.tileCount < tileDeficitThreshold
                and not (BotStateQueries.is_all_in(bot) or bot.all_in_losing_counter > 50)
        ):
            logbook.info("ayyyyyyyyyyyyyyyyyyyyyyyyy set enemyGather to True because we're behind on tiles")
            enemyGather = True
            bot.makingUpTileDeficit = True
        else:
            bot.makingUpTileDeficit = False

        if bot.defend_economy:
            logbook.info("we're playing defensively, neutralGather and enemyGather set to false...")
            neutralGather = False
            enemyGather = False

        if not tryGather:
            return None

        return BotGatherOps.get_main_gather_move(bot, defenseCriticalTileSet, leafMoves, enemyGather, neutralGather, needToKillTiles)

    @staticmethod
    def get_main_gather_move(
            bot,
            defenseCriticalTileSet: typing.Set[Tile],
            leafMoves: typing.List[Move] | None,
            enemyGather: bool = False,
            neutralGather: bool = False,
            needToKillTiles: typing.List[Tile] | None = None,
    ) -> Move | None:
        if not needToKillTiles:
            needToKillTiles = []
        if not leafMoves:
            leafMoves = []

        gathString = ""
        gathStartTime = time.perf_counter()
        gatherTargets = bot.target_player_gather_targets.copy()
        if len(gatherTargets) == 2:
            gatherTargets = set()
            gatherTargets.add(bot.general)
            gatherTargets.update(bot.launchPoints)
        gatherNegatives = defenseCriticalTileSet.copy()
        if bot.curPath:
            nextMove = bot.curPath.get_first_move()
            if nextMove:
                gatherNegatives.add(nextMove.source)

        genPlayer = bot._map.players[bot.general.player]

        inEnTerrSet = set()
        sumEnTerrArmy = 0
        if bot.targetPlayer >= 0:
            for tile in genPlayer.tiles:
                if bot._map.is_player_on_team_with(bot.territories.territoryMap[tile], bot.targetPlayer):
                    inEnTerrSet.add(tile)
                    sumEnTerrArmy += tile.army - 1
        isNonDominantFfa = BotStateQueries.is_still_ffa_and_non_dominant(bot)
        if (len(inEnTerrSet) < bot.player.tileCount // 6
                or (bot.targetPlayer != -1
                    and bot.opponent_tracker.get_current_team_scores_by_player(bot.player.index).standingArmy - sumEnTerrArmy < bot.opponent_tracker.get_current_team_scores_by_player(bot.targetPlayer).standingArmy * 0.9)):
            if not bot.currently_forcing_out_of_play_gathers and not bot.defend_economy and not isNonDominantFfa:
                gatherNegatives.update(inEnTerrSet)

        if bot.teammate_general is not None:
            allyPlayer = bot._map.players[bot.teammate_general.player]
            for tile in allyPlayer.tiles:
                if bot._map.is_player_on_team_with(bot.territories.territoryMap[tile], bot.targetPlayer):
                    gatherNegatives.add(tile)

        if bot.targetPlayer == -1:
            enemyGather = False

        if bot.timings.disallowEnemyGather:
            logbook.info("Enemy gather was disallowed in timings, skipping enemy and neutral gathering.")
            enemyGather = False
            neutralGather = False

        if (enemyGather or neutralGather) and not BotStateQueries.is_all_in(bot, ) and bot._map.turn >= 150:
            gathString += f" +leaf(enemy {enemyGather})"
            leafPruneStartTime = time.perf_counter()

            shortestLength = bot.shortest_path_to_target_player.length
            if not BotStateQueries.is_all_in(bot, ) and not bot.defend_economy and enemyGather and bot._map.turn >= 150 and leafMoves and not isNonDominantFfa:
                goodLeaves = bot.board_analysis.find_flank_leaves(
                    leafMoves,
                    minAltPathCount=2,
                    maxAltLength=shortestLength + shortestLength // 3)
                for goodLeaf in goodLeaves:
                    BotRendering.mark_tile(bot, goodLeaf.dest, 255)
                    gatherNegatives.add(goodLeaf.dest)

            if not isNonDominantFfa:
                for leaf in filter(lambda move: move.dest.player == bot.targetPlayer or (neutralGather and move.dest.player == -1), leafMoves):
                    if (
                            not (leaf.dest.isCity and leaf.dest.player == -1)
                            and leaf.dest not in bot.target_player_gather_targets
                    ):
                        if leaf.dest.player != bot.targetPlayer and leaf.dest.player >= 0:
                            continue
                        useTile = leaf.source
                        if leaf.dest.player == bot.targetPlayer:
                            useTile = leaf.dest

                        if (
                                bot.targetPlayer != -1
                                and not neutralGather
                                and (leaf.dest.player == -1 or leaf.source.player == -1)
                        ):
                            continue

                        if (
                            bot.territories.territoryMap[useTile] != bot.general.player
                            and bot.territories.territoryMap[useTile] not in bot._map.teammates
                            and (
                                BotPathingUtils.distance_from_target_path(bot, leaf.source) <= BotPathingUtils.distance_from_target_path(bot, leaf.dest)
                                or BotPathingUtils.distance_from_target_path(bot, leaf.source) > bot.shortest_path_to_target_player.length / 3
                            )
                        ):
                            continue

                        gatherNegatives.add(useTile)

            logbook.info(f"pruning leaves and stuff took {time.perf_counter() - leafPruneStartTime:.4f}")

        forceGatherToEnemy = BM.BotDefense.BotDefense.should_force_gather_to_enemy_tiles(bot, )

        gatherPriorities = BotGatherOps.get_gather_tiebreak_matrix(bot, )

        usingNeedToKill = len(needToKillTiles) > 0 and not bot.flanking and not bot.defend_economy

        if usingNeedToKill:
            gathString += " +needToKill"
            for tile in needToKillTiles:
                if tile in gatherTargets and bot.distance_from_general(tile) > 3:
                    continue

                if not forceGatherToEnemy:
                    BotRendering.mark_tile(bot, tile, 100)

                if forceGatherToEnemy:
                    def tile_remover(curTile: Tile):
                        if curTile not in needToKillTiles and curTile in gatherTargets:
                            gatherTargets.remove(curTile)

                    SearchUtils.breadth_first_foreach_fast_no_neut_cities(bot._map, [tile], 2, tile_remover)

                    gatherTargets.add(tile)

            if bot.timings.in_quick_expand_split(bot._map.turn) and forceGatherToEnemy:
                negCopy = gatherNegatives.copy()
                for pathTile in bot.target_player_gather_path.tileList:
                    negCopy.add(pathTile)

                targetTurns = 4
                with bot.perf_timer.begin_move_event(f'Timing Gather QE to enemy needToKill tiles depth {targetTurns}'):
                    move = BotGatherOps.timing_gather(
                        bot,
                        needToKillTiles,
                        negCopy,
                        skipTiles=set(genPlayer.cities),
                        force=True,
                        priorityTiles=None,
                        targetTurns=targetTurns,
                        includeGatherTreeNodesThatGatherNegative=False,
                        priorityMatrix=gatherPriorities)
                if move is not None:
                    if not isinstance(bot.curPath, MoveListPath):
                        bot.curPath = None
                    bot.info(
                        f"GATHER QE needToKill{gathString}! Gather move: {move} Duration {time.perf_counter() - gathStartTime:.4f}")
                    if not bot._map.is_player_on_team_with(move.dest.player, bot.general.player) and move.dest.player != -1:
                        bot.curPath = None
                    return BotRepetition.move_half_on_repetition(bot, move, 6, 4)
                else:
                    logbook.info("No QE needToKill gather move found")
        else:
            needToKillTiles = None

        with bot.perf_timer.begin_move_event(f'Timing Gather (normal / defensive)'):
            gatherNegatives = BotGatherOps.get_timing_gather_negatives_unioned(bot, gatherNegatives)

            if bot.currently_forcing_out_of_play_gathers or bot.defend_economy:
                if bot.currently_forcing_out_of_play_gathers:
                    gathString += " +out of play"
                if bot.defend_economy:
                    gathString += " +ecDef"

                genPlayer = bot._map.players[bot.general.player]
                for tile in genPlayer.tiles:
                    if tile in bot.board_analysis.core_play_area_matrix and tile not in bot.tiles_gathered_to_this_cycle and tile.army > 1:
                        gatherPriorities.raw[tile.tile_index] -= 0.2
                    if tile not in bot.board_analysis.extended_play_area_matrix and tile not in bot.tiles_gathered_to_this_cycle and tile.army > 1:
                        gatherPriorities.raw[tile.tile_index] += 0.2

            useTrueValueGathered = False
            tgTurns = -1
            includeGatherTreeNodesThatGatherNegative = bot.defend_economy
            distancePriorities = bot.board_analysis.intergeneral_analysis.bMap
            if bot.defend_economy:
                tgTurns = -1
                useTrueValueGathered = True
                gatherTargets = gatherTargets.copy()
                if bot.enemy_attack_path is not None:
                    gatherTargets = bot.enemy_attack_path.tileSet
                    if bot.opponent_tracker.winning_on_economy(byRatio=1.1, offset=-25):
                        gatherPriorities = None
                        tgTurns = bot._map.remainingCycleTurns - 5
                        useTrueValueGathered = False
                        includeGatherTreeNodesThatGatherNegative = True
                        distancePriorities = bot.board_analysis.intergeneral_analysis.aMap
                        gatherNegatives.update(bot.win_condition_analyzer.defend_cities)
                        gathString = f" +NO_MAT_RISKPATH {tgTurns}t" + gathString
                    else:
                        gathString = " +RISKPATH" + gathString
                else:
                    gatherTargets.update([t for t in bot.board_analysis.intergeneral_analysis.shortestPathWay.tiles if not t.isObstacle])

                for t in gatherTargets:
                    bot.viewInfo.add_targeted_tile(t, TargetStyle.WHITE, radiusReduction=11)

            move = BotGatherOps.timing_gather(
                bot,
                [t for t in gatherTargets],
                gatherNegatives,
                skipTiles=None,
                force=True,
                priorityTiles=None,
                priorityMatrix=gatherPriorities,
                includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
                distancePriorities=distancePriorities,
                useTrueValueGathered=useTrueValueGathered,
                targetTurns=tgTurns,
                pruneToValuePerTurn=bot.defend_economy)

        if move is not None:
            if move.dest.player != bot.player.index and move.dest not in bot.target_player_gather_targets and not bot.flanking and needToKillTiles is not None and move.dest in needToKillTiles:
                bot.timings.splitTurns += 1
                bot.timings.launchTiming += 1

            if move.source.isCity or move.source.isGeneral:
                bot.cities_gathered_this_cycle.add(move.source)

            if move.dest.isCity and move.dest.player == bot.player.index and move.dest in bot.cities_gathered_this_cycle:
                bot.cities_gathered_this_cycle.remove(move.dest)

            if not isinstance(bot.curPath, MoveListPath):
                bot.curPath = None
            bot.info(
                f"GATHER {gathString}! Gather move: {move} Duration {time.perf_counter() - gathStartTime:.4f}")
            return BotRepetition.move_half_on_repetition(bot, move, 6, 4)
        else:
            logbook.info("No gather move found")

        return None

    @staticmethod
    def get_capture_first_tree_move_prio_func(bot) -> typing.Callable[[Tile, typing.Any], typing.Any]:
        def capture_first_value_func(curTile: Tile, currentPriorityObject):
            lastTile = None
            if currentPriorityObject:
                (_, _, lastTile) = currentPriorityObject
            return (
                lastTile is None or not bot._map.is_tile_friendly(lastTile),
                curTile.isSwamp,
                curTile
            )

        return capture_first_value_func

    @staticmethod
    def get_gather_to_target_tile(
            bot,
            target: Tile,
            maxTime: float,
            gatherTurns: int,
            negativeSet: typing.Set[Tile] | None = None,
            targetArmy: int = -1,
            useTrueValueGathered=False,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        targets = [target]
        gatherTuple = BotGatherOps.get_gather_to_target_tiles(
            bot,
            targets,
            maxTime,
            gatherTurns,
            negativeSet,
            targetArmy,
            useTrueValueGathered=useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            maximizeArmyGatheredPerTurn=maximizeArmyGatheredPerTurn)
        return gatherTuple

    @staticmethod
    def timing_gather(
            bot,
            startTiles: typing.List[Tile],
            negativeTiles: typing.Set[Tile] | None = None,
            skipTiles: typing.Set[Tile] | None = None,
            force=False,
            priorityTiles: typing.Set[Tile] | None = None,
            targetTurns=-1,
            includeGatherTreeNodesThatGatherNegative=False,
            useTrueValueGathered: bool = False,
            pruneToValuePerTurn: bool = False,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            distancePriorities: MapMatrixInterface[int] | None = None,
            logStuff: bool = False
    ) -> Move | None:
        turnOffset = bot._map.turn + bot.timings.offsetTurns
        turnCycleOffset = turnOffset % bot.timings.cycleTurns

        gatherNodeMoveSelectorFunc = BotGatherOps._get_tree_move_default_value_func(bot, )
        if bot.likely_kill_push:
            potThreat = bot.dangerAnalyzer.fastestPotentialThreat
            if potThreat is None and bot.enemy_attack_path is not None:
                aa = ArmyAnalyzer(bot._map, bot.enemy_attack_path.start.tile, bot.enemy_attack_path.tail.tile)
                potThreat = ThreatObj(bot.enemy_attack_path.length, bot.enemy_attack_path.value, bot.enemy_attack_path, ThreatType.Vision, armyAnalysis=aa)
            if potThreat is not None:
                gatherNodeMoveSelectorFunc = BM.BotDefense.BotDefense.get_defense_tree_move_prio_func(bot, potThreat)

        if force or (bot._map.turn >= 50 and turnCycleOffset < bot.timings.splitTurns and startTiles is not None and len(startTiles) > 0):
            bot.finishing_exploration = False
            if targetTurns != -1:
                depth = targetTurns
            else:
                depth = bot.timings.splitTurns - turnCycleOffset

                if pruneToValuePerTurn and depth < 10:
                    depth = 10

                if depth <= 0:
                    depth += bot.timings.cycleTurns

            if depth > GATHER_SWITCH_POINT:
                with bot.perf_timer.begin_move_event(f"USING OLD MST GATH depth {depth}"):
                    gatherNodes = BotGatherOps.build_mst(bot, startTiles, 1.0, depth - 1, negativeTiles)
                    gatherNodes = Gather.prune_mst_to_turns(
                        gatherNodes,
                        depth - 1,
                        bot.general.player,
                        preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                        viewInfo=bot.viewInfo if bot.info_render_gather_values else None,
                        noLog=not logStuff)
                gatherMove = BotGatherOps.get_tree_move_default(bot, gatherNodes)
                if gatherMove is not None:
                    bot.viewInfo.add_info_line(
                        f"OLD LEAF MST GATHER MOVE! {gatherMove.source.x},{gatherMove.source.y} -> {gatherMove.dest.x},{gatherMove.dest.y}  leafGatherDepth: {depth}")
                    bot.gatherNodes = gatherNodes
                    return BotRepetition.move_half_on_repetition(bot, gatherMove, 6)
            else:
                skipFunc = None
                if BotStateQueries.is_still_ffa_and_non_dominant(bot):
                    skipFunc = lambda tile, tilePriorityObject: not tile.discovered

                startTileStr = 'no start tiles'
                if startTiles and len(startTiles) > 0:
                    startTiles = [t for t in startTiles if t is not None]
                    startTileStr = f'@{" | ".join([str(t) for t in sorted(startTiles, key=lambda st: bot.board_analysis.intergeneral_analysis.bMap.raw[st.tile_index])])}'
                bot.info(f'GathParams: depth {depth}, mat {str(priorityMatrix is not None)[0]}, useTrue {str(useTrueValueGathered)[0]}, incNeg {str(includeGatherTreeNodesThatGatherNegative)[0]}, {startTileStr}')

                if distancePriorities is None:
                    distancePriorities = bot.board_analysis.intergeneral_analysis.bMap
                move, value, turnsUsed, gatherNodes = BotGatherOps.get_gather_to_target_tiles(
                    bot,
                    startTiles,
                    0.05,
                    depth,
                    negativeTiles,
                    useTrueValueGathered=useTrueValueGathered,
                    includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
                    skipTiles=skipTiles,
                    distPriorityMap=distancePriorities,
                    priorityMatrix=priorityMatrix,
                    shouldLog=logStuff,
                )

                if gatherNodes is None:
                    bot.info(f'ERR timing_gather failed {depth}t with get_gather_to_target_tiles...? @{startTiles}')
                    for t in startTiles:
                        bot.viewInfo.add_targeted_tile(t, TargetStyle.TEAL)
                    value, turnsUsed, gatherNodes = Gather.knapsack_depth_gather_with_values(
                        bot._map,
                        startTiles,
                        depth,
                        negativeTiles=negativeTiles,
                        searchingPlayer=bot.general.player,
                        skipFunc=skipFunc,
                        viewInfo=bot.viewInfo if bot.info_render_gather_values else None,
                        skipTiles=skipTiles,
                        distPriorityMap=distancePriorities,
                        priorityTiles=priorityTiles,
                        useTrueValueGathered=useTrueValueGathered,
                        includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
                        incrementBackward=False,
                        priorityMatrix=priorityMatrix,
                        shouldLog=logStuff)

                if pruneToValuePerTurn:
                    minGather = value // 3
                    reason = ''
                    if bot.defend_economy:
                        minGather = 4 * value // 5
                        reason = 'ECON DEF '
                    prefer = set()
                    for t in bot.player.tiles:
                        if t.army <= 1:
                            prefer.add(t)
                    prunedCount, prunedValue, gatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                        gatherNodes,
                        minArmy=minGather,
                        searchingPlayer=bot.general.player,
                        teams=MapBase.get_teams_array(bot._map),
                        viewInfo=bot.viewInfo if bot.info_render_gather_values else None,
                        allowNegative=includeGatherTreeNodesThatGatherNegative,
                        noLog=not logStuff,
                        allowBranchPrune=True
                    )
                    turnsUsed = prunedCount
                    value = prunedValue
                    bot.viewInfo.add_info_line(f"{reason}pruned to max G/T {prunedValue:.1f}/{prunedCount}t  {prunedValue/max(1, prunedCount):.2f}vt (min {minGather:.0f})  (from {value:.1f}/{turnsUsed}t  {value/max(1, turnsUsed):.2f}vt)")
                    turnInCycle = bot.timings.get_turn_in_cycle(bot._map.turn)
                    if prunedCount + turnInCycle > bot.timings.splitTurns:
                        newSplit = prunedCount + turnInCycle
                        bot.viewInfo.add_info_line(f'updating timings to gatherSplit {newSplit} due to defensive gather')
                        bot.timings.splitTurns = newSplit
                        bot.timings.launchTiming = max(bot.timings.splitTurns, bot.timings.launchTiming)

                bot.gatherNodes = gatherNodes

                if bot.info_render_gather_values and priorityMatrix:
                    for t in bot._map.reachable_tiles:
                        val = priorityMatrix[t]
                        if val:
                            bot.viewInfo.topRightGridText[t] = f'g{str(round(val, 3)).lstrip("0").replace("-0", "-")}'
                move = BotGatherOps.get_tree_move_default(bot, bot.gatherNodes, gatherNodeMoveSelectorFunc)
                if move is not None:
                    bot.curPath = None
                    bot.curPath = BotGatherOps.convert_gather_to_move_list_path(bot, gatherNodes, turnsUsed, value, gatherNodeMoveSelectorFunc)
                    return BotRepetition.move_half_on_repetition(bot, move, 6, 4)
                else:
                    logbook.info("NO MOVE WAS RETURNED FOR timing_gather?????????????????????")
        else:
            bot.finishing_exploration = True
            bot.viewInfo.add_info_line("finishExp=True in timing_gather because outside cycle...?")
            logbook.info(f"No timing move because outside gather timing window. Timings: {str(bot.timings)}")
        return None

    @staticmethod
    def get_defensive_gather_to_target_tiles(
            bot,
            targets,
            maxTime,
            gatherTurns,
            negativeSet=None,
            targetArmy=-1,
            useTrueValueGathered=False,
            leafMoveSelectionValueFunc=None,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False,
            additionalIncrement: int = 0,
            distPriorityMap: MapMatrix[int] | None = None,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            skipTiles: TileSet | None = None,
            shouldLog: bool = False,
            fastMode: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        if useTrueValueGathered and targetArmy > -1:
            targetArmy += 1

        if additionalIncrement != 0 and targetArmy > 0:
            targetArmy = targetArmy + additionalIncrement * gatherTurns // 2

        gatherNodes = Gather.knapsack_depth_gather(
            bot._map,
            targets,
            gatherTurns,
            targetArmy,
            distPriorityMap=distPriorityMap,
            negativeTiles=negativeSet,
            searchingPlayer=bot.general.player,
            viewInfo=bot.viewInfo if bot.info_render_gather_values else None,
            useTrueValueGathered=useTrueValueGathered,
            incrementBackward=False,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            priorityMatrix=priorityMatrix,
            cutoffTime=time.perf_counter() + maxTime,
            shouldLog=shouldLog,
            fastMode=fastMode)

        if maximizeArmyGatheredPerTurn:
            turns, value, gatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                gatherNodes,
                targetArmy,
                searchingPlayer=bot.general.player,
                teams=MapBase.get_teams_array(bot._map),
                additionalIncrement=additionalIncrement,
                preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                viewInfo=bot.viewInfo if bot.info_render_gather_values else None)

        totalValue = 0
        turns = 0
        for gather in gatherNodes:
            logbook.info(f"gatherNode {gather.tile.toString()} value {gather.value}")
            totalValue += gather.value
            turns += gather.gatherTurns

        logbook.info(
            f"gather_to_target_tiles totalValue was {totalValue}. Setting gatherNodes for visual debugging regardless of using them")
        if totalValue > targetArmy - gatherTurns // 2:
            move = BotGatherOps.get_tree_move_default(bot, gatherNodes, valueFunc=leafMoveSelectionValueFunc)
            if move is not None:
                bot.gatherNodes = gatherNodes
                return BotRepetition.move_half_on_repetition(bot, move, 4), totalValue, turns, gatherNodes
            else:
                logbook.info("Gather returned no moves :(")
        else:
            logbook.info(f"Value {totalValue} was too small to return... (needed {targetArmy}) :(")
        return None, -1, -1, None

    @staticmethod
    def get_gather_tiebreak_matrix(bot) -> MapMatrixInterface[float]:
        matrix = MapMatrix(bot._map, 0.0)

        desertPenalty = 0.25
        for tile in bot.board_analysis.backwards_tiles:
            if tile.army > 2:
                matrix.raw[tile.tile_index] += 0.45
            elif tile.army > 1:
                matrix.raw[tile.tile_index] += 0.25

        for tile in bot._map.swamps:
            matrix.raw[tile.tile_index] -= 2.0

        for tile in bot._map.deserts:
            matrix.raw[tile.tile_index] -= desertPenalty

        if bot.expansion_plan is not None:
            if bot.expansion_plan.selected_option is not None:
                for tile in bot.expansion_plan.selected_option.tileSet:
                    matrix.raw[tile.tile_index] -= 0.2
            for path in bot.expansion_plan.all_paths:
                for tile in path.tileSet:
                    matrix.raw[tile.tile_index] -= 0.05

        isNonDomFfa = BotStateQueries.is_still_ffa_and_non_dominant(bot)

        for p in bot._map.get_teammates(bot._map.player_index):
            for tile in bot._map.players[p].tiles:
                if not isNonDomFfa or bot._map.turn > 200:
                    if tile in bot.board_analysis.intergeneral_analysis.shortestPathWay.tiles:
                        matrix.raw[tile.tile_index] -= 0.4

                    if tile.army <= 1:
                        matrix.raw[tile.tile_index] -= 0.5

                if tile.isDesert:
                    matrix.raw[tile.tile_index] += desertPenalty

                isAllFriendly = True
                for adj in tile.movable:
                    if not adj.isObstacle and not bot._map.is_tile_friendly(adj):
                        isAllFriendly = False
                        break

                if isAllFriendly and bot.territories.territoryDistances[bot.targetPlayer].raw[tile.tile_index] > 3:
                    matrix.raw[tile.tile_index] += min(0.49, 0.04 * bot.territories.territoryDistances[bot.targetPlayer].raw[tile.tile_index])

                if not isAllFriendly and not isNonDomFfa:
                    matrix.raw[tile.tile_index] -= 0.25

                if tile not in bot.board_analysis.extended_play_area_matrix and tile.army > 1:
                    distToShortest = bot.board_analysis.shortest_path_distances.raw[tile.tile_index]
                    if distToShortest < 1000:
                        matrix.raw[tile.tile_index] += min(0.49, 0.03 * distToShortest)

                if bot.info_render_gather_matrix_values:
                    matrixVal = matrix.raw[tile.tile_index]
                    if matrixVal:
                        bot.viewInfo.topRightGridText.raw[tile.tile_index] = f'g{str(round(matrixVal, 3)).lstrip("0").replace("-0", "-")}'

        for city in bot.cities_gathered_this_cycle:
            matrix.raw[city.tile_index] = -1.0

        return matrix

    @staticmethod
    def build_mst(bot, startTiles, maxTime=0.1, maxDepth=150, negativeTiles: typing.Set[Tile] = None, avoidTiles=None, priorityFunc=None):
        LOG_TIME = False
        searchingPlayer = bot._map.player_index
        frontier = SearchUtils.HeapQueue()
        visitedBack = MapMatrix(bot._map)

        if isinstance(startTiles, dict):
            for tile in startTiles.keys():
                if isinstance(startTiles[tile], int):
                    distance = startTiles[tile]
                    frontier.put((distance, (0, 0, distance, tile.x, tile.y), tile, tile))
                else:
                    (startPriorityObject, distance) = startTiles[tile]
                    startVal = startPriorityObject
                    frontier.put((distance, startVal, tile, tile))
        else:
            startTiles = set(startTiles)
            if priorityFunc is not None:
                raise AssertionError("You MUST use a dict of startTiles if not using the emptyVal priorityFunc")
            for tile in startTiles:
                negEnemyCount = 0
                if tile.player == bot.targetPlayer:
                    negEnemyCount = -1
                frontier.put((0, (0, 0, 0, tile.x, tile.y), tile, tile))

        if not priorityFunc:
            def default_priority_func(nextTile, currentPriorityObject):
                (prio, negArmy, dist, xSum, ySum) = currentPriorityObject
                nextArmy = 0 - negArmy - 1
                if negativeTiles is None or nextTile not in negativeTiles:
                    if searchingPlayer == nextTile.player:
                        nextArmy += nextTile.army
                    else:
                        nextArmy -= nextTile.army
                dist += 1
                return 0 - nextArmy / dist, 0 - nextArmy, dist, xSum + nextTile.x, ySum + nextTile.y

            priorityFunc = default_priority_func

        start = time.perf_counter()
        while frontier.queue:
            (dist, curPriorityVal, current, cameFrom) = frontier.get()
            if visitedBack.raw[current.tile_index] is not None:
                continue
            if avoidTiles is not None and current in avoidTiles:
                continue
            if current.isMountain or (not current.discovered and current.isNotPathable):
                continue
            if current.isCity and current.player != searchingPlayer and current not in startTiles:
                dist += 7
            visitedBack.raw[current.tile_index] = cameFrom
            if dist <= maxDepth:
                dist += 1
                for next in current.movable:
                    nextPriorityVal = priorityFunc(next, curPriorityVal)
                    frontier.put((dist, nextPriorityVal, next, current))
        if LOG_TIME:
            logbook.info(f"BUILD-MST DURATION: {time.perf_counter() - start:.3f}")

        result = BotGatherOps.build_mst_rebuild(bot, startTiles, visitedBack, bot._map.player_index)

        return result

    @staticmethod
    def build_mst_rebuild(bot, startTiles, fromMap, searchingPlayer):
        results = []
        for tile in startTiles:
            gather = BotGatherOps.get_gather_mst(bot, tile, None, fromMap, 0, searchingPlayer)
            if gather.tile.player == searchingPlayer:
                gather.value -= gather.tile.army
            else:
                gather.value += gather.tile.army

            results.append(gather)
        return results

    @staticmethod
    def get_gather_mst(bot, tile, fromTile, fromMap, turn, searchingPlayer):
        gatherTotal = tile.army
        turnTotal = 1
        if tile.player != searchingPlayer:
            gatherTotal = 0 - tile.army
        gatherTotal -= 1
        thisNode = GatherTreeNode(tile, fromTile, turn)
        if tile.player == -1:
            thisNode.neutrals = 1
        for move in tile.movable:
            if move == fromTile:
                continue
            if fromMap.raw[move.tile_index] != tile:
                continue
            gather = BotGatherOps.get_gather_mst(bot, move, tile, fromMap, turn + 1, searchingPlayer)
            if gather.value > 0:
                gatherTotal += gather.value
                turnTotal += gather.gatherTurns
                thisNode.children.append(gather)

        thisNode.value = gatherTotal
        thisNode.gatherTurns = turnTotal
        return thisNode

    @staticmethod
    def get_tree_move_non_city_leaf_count(bot, gathers):
        count = 0
        for gather in gathers:
            foundCity, countNonCityLeaves = BotGatherOps._get_tree_move_non_city_leaf_count_recurse(bot, gather)
            count += countNonCityLeaves
        return count

    @staticmethod
    def _get_tree_move_non_city_leaf_count_recurse(bot, gather):
        count = 0
        thisNodeFoundCity = False
        for child in gather.children:
            foundCity, countNonCityLeaves = BotGatherOps._get_tree_move_non_city_leaf_count_recurse(bot, child)
            logbook.info(f"child {child.tile.toString()} foundCity {foundCity} countNonCityLeaves {countNonCityLeaves}")
            count += countNonCityLeaves
            if foundCity:
                thisNodeFoundCity = True
        if bot._map.is_tile_friendly(gather.tile) and (gather.tile.isCity or gather.tile.isGeneral):
            thisNodeFoundCity = True
        if not thisNodeFoundCity:
            count += 1
        return thisNodeFoundCity, count

    @staticmethod
    def _get_tree_move_default_value_func(bot) -> typing.Callable[[Tile, typing.Tuple], typing.Tuple | None]:
        def default_value_func(currentTile, currentPriorityObject):
            negCityCount = negDistFromPlayArea = army = unfriendlyTileCount = 0
            curIsOurCity = True
            if currentPriorityObject is not None:
                (_, nextIsOurCity, negCityCount, unfriendlyTileCount, negDistFromPlayArea, army, curIsOurCity) = currentPriorityObject
                army -= 1
            nextIsOurCity = curIsOurCity
            curIsOurCity = True
            if bot._map.is_tile_friendly(currentTile):
                if currentTile.isGeneral or currentTile.isCity:
                    negCityCount -= 1
            else:
                if currentTile.isGeneral or currentTile.isCity and army + 2 <= currentTile.army:
                    curIsOurCity = False
                unfriendlyTileCount += 1

            negDistFromPlayArea = 0 - bot.board_analysis.intergeneral_analysis.bMap.raw[currentTile.tile_index]

            if bot._map.is_tile_friendly(currentTile):
                army += currentTile.army
            else:
                army -= currentTile.army
            return currentTile.isSwamp, nextIsOurCity, negCityCount, unfriendlyTileCount, negDistFromPlayArea, army, curIsOurCity

        return default_value_func

    @staticmethod
    def get_tree_move_default(
            bot,
            gathers: typing.List[GatherTreeNode],
            valueFunc: typing.Callable[[Tile, typing.Tuple], typing.Tuple | None] | None = None,
            pop: bool = False
    ) -> Move | None:
        if valueFunc is None:
            valueFunc = BotGatherOps._get_tree_move_default_value_func(bot, )

        move = Gather.get_tree_move(gathers, valueFunc, pop=pop)
        if move is not None and move.source.player != bot.general.player:
            logbook.error(f'returned a move {move} that wasnt from our tile. Replacing with another move further in the list...')
            bot.viewInfo.add_info_line(f'returned a move {move} that wasnt from our tile. Replacing with another move further in the list...')
            moves = Gather.get_tree_moves(gathers, valueFunc, pop=False)
            newMove = None
            for newMove in moves:
                if newMove.source.player == bot.general.player and newMove.source.army > 1:
                    break
            if newMove is not None and newMove.source.player == bot.general.player:
                bot.viewInfo.add_info_line(f'GTMD RET BAD {move} - Replacing with {newMove}')
                return newMove
            bot.viewInfo.add_info_line(f'GTMD RET BAD {move} NO GOOD MOVE FOUND')
            return None
        return move

    @staticmethod
    def get_gather_to_target_tiles(
            bot,
            targets,
            maxTime,
            gatherTurns,
            negativeSet=None,
            targetArmy=-1,
            useTrueValueGathered=False,
            leafMoveSelectionValueFunc=None,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False,
            additionalIncrement: int = 0,
            distPriorityMap: MapMatrix[int] | None = None,
            priorityMatrix: MapMatrixInterface[float] | None = None,
            skipTiles: TileSet | None = None,
            shouldLog: bool = False,
            fastMode: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        if useTrueValueGathered and targetArmy > -1:
            targetArmy += 1

        if bot.gather_use_pcst and gatherTurns > 0 and targetArmy < 0 and not isinstance(targets, dict):
            convertedTargets: typing.List[Tile] = targets

            gathCapPlan = Gather.gather_approximate_turns_to_tiles(
                bot._map,
                rootTiles=convertedTargets,
                approximateTargetTurns=gatherTurns,
                asPlayer=bot.general.player,
                gatherMatrix=priorityMatrix,
                captureMatrix=priorityMatrix,
                negativeTiles=negativeSet,
                skipTiles=skipTiles,
                prioritizeCaptureHighArmyTiles=False,
                useTrueValueGathered=useTrueValueGathered,
                includeGatherPriorityAsEconValues=True,
                includeCapturePriorityAsEconValues=True,
                logDebug=shouldLog,
                viewInfo=bot.viewInfo if bot.info_render_gather_values else None)

            if gathCapPlan is not None:

                gatherNodes = gathCapPlan.root_nodes

                if maximizeArmyGatheredPerTurn:
                    bot.info(
                        f"pcst gath (pre-prune) achieved {gathCapPlan.gathered_army} turns {gathCapPlan.gather_turns} (target turns {gatherTurns})")
                    turns, value, gatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                        gatherNodes,
                        targetArmy,
                        searchingPlayer=bot.general.player,
                        teams=MapBase.get_teams_array(bot._map),
                        additionalIncrement=additionalIncrement,
                        preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                        viewInfo=bot.viewInfo if bot.info_render_gather_values else None)

                totalValue = 0
                turns = 0
                for gather in gatherNodes:
                    logbook.info(f"gatherNode {gather.tile.toString()} value {gather.value}")
                    totalValue += gather.value
                    turns += gather.gatherTurns
                bot.info(
                    f"pcst gath achieved {totalValue} turns {gathCapPlan.gather_turns} (target turns {gatherTurns})")
                if totalValue > targetArmy - gatherTurns // 2:
                    move = BotGatherOps.get_tree_move_default(bot, gatherNodes, valueFunc=leafMoveSelectionValueFunc)
                    if move is not None:
                        bot.gatherNodes = gatherNodes
                        return BotRepetition.move_half_on_repetition(bot, move, 4), totalValue, turns, gatherNodes
                    else:
                        logbook.info("Gather returned no moves :(")
                else:
                    logbook.info(f"Value {totalValue} was too small to return... (needed {targetArmy}) :(")
        elif gatherTurns > GATHER_SWITCH_POINT:
            logbook.info(f"    gather_to_target_tiles  USING OLD GATHER DUE TO gatherTurns {gatherTurns}")
            gatherNodes = BotGatherOps.build_mst(bot, targets, maxTime, gatherTurns - 1, negativeSet)
            gatherNodes = Gather.prune_mst_to_turns(
                gatherNodes,
                gatherTurns - 1,
                bot.general.player,
                viewInfo=bot.viewInfo if bot.info_render_gather_values else None,
                preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None)

            if maximizeArmyGatheredPerTurn:
                turns, value, gatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                    gatherNodes,
                    targetArmy,
                    searchingPlayer=bot.general.player,
                    teams=MapBase.get_teams_array(bot._map),
                    additionalIncrement=additionalIncrement,
                    preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                    viewInfo=bot.viewInfo if bot.info_render_gather_values else None)

            gatherMove = BotGatherOps.get_tree_move_default(bot, gatherNodes, valueFunc=leafMoveSelectionValueFunc)
            value = 0
            turns = 0
            for node in gatherNodes:
                value += node.value
                turns += node.gatherTurns
            if gatherMove is not None:
                bot.info(
                    f"gather_to_target_tiles OLD GATHER {gatherMove.source.toString()} -> {gatherMove.dest.toString()}  gatherTurns: {gatherTurns}")
                bot.gatherNodes = gatherNodes
                return BotRepetition.move_half_on_repetition(bot, gatherMove, 6), value, turns, gatherNodes
        else:
            if additionalIncrement != 0 and targetArmy > 0:
                targetArmy = targetArmy + additionalIncrement * gatherTurns // 2
            if bot.gather_use_max_set and not isinstance(targets, dict):
                with bot.perf_timer.begin_move_event(f'gath_max_set {gatherTurns}t'):
                    gatherMatrix = BotGatherOps.get_gather_tiebreak_matrix(bot, )
                    captureMatrix = BM.BotExpansionOps.BotExpansionOps.get_expansion_weight_matrix(bot, )
                    valueMatrix = Gather.build_gather_capture_pure_value_matrix(
                        bot._map,
                        bot.general.player,
                        negativeTiles=negativeSet,
                        gatherMatrix=gatherMatrix,
                        captureMatrix=captureMatrix,
                        useTrueValueGathered=useTrueValueGathered,
                        prioritizeCaptureHighArmyTiles=False)
                    armyCostMatrix = Gather.build_gather_capture_pure_value_matrix(
                        bot._map,
                        bot.general.player,
                        negativeTiles=negativeSet,
                        gatherMatrix=gatherMatrix,
                        captureMatrix=captureMatrix,
                        useTrueValueGathered=True,
                        prioritizeCaptureHighArmyTiles=False)
                    plan = Gather.gather_max_set_iterative_plan(
                        bot._map,
                        targets,
                        gatherTurns,
                        valueMatrix,
                        armyCostMatrix,
                        renderLive=False,
                        viewInfo=None,
                        searchingPlayer=bot.general.player,
                        fastMode=True,
                        cutoffTime=time.perf_counter() + maxTime
                    )
                    gatherNodes = []
                    if plan and plan.root_nodes:
                        gatherNodes = plan.root_nodes
            else:
                with bot.perf_timer.begin_move_event(f'knapsack_max_gather {gatherTurns}t, {targetArmy}a'):
                    gatherNodes = Gather.knapsack_max_gather(
                        bot._map,
                        targets,
                        gatherTurns,
                        targetArmy,
                        distPriorityMap=distPriorityMap,
                        negativeTiles=negativeSet,
                        searchingPlayer=bot.general.player,
                        viewInfo=bot.viewInfo if bot.info_render_gather_values else None,
                        useTrueValueGathered=useTrueValueGathered,
                        incrementBackward=False,
                        includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
                        priorityMatrix=priorityMatrix,
                        cutoffTime=time.perf_counter() + maxTime,
                        shouldLog=shouldLog,
                        fastMode=fastMode)

            if maximizeArmyGatheredPerTurn:
                turns, value, gatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                    gatherNodes,
                    targetArmy,
                    searchingPlayer=bot.general.player,
                    teams=MapBase.get_teams_array(bot._map),
                    additionalIncrement=additionalIncrement,
                    preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                    viewInfo=bot.viewInfo if bot.info_render_gather_values else None)

            totalValue = 0
            turns = 0
            for gather in gatherNodes:
                logbook.info(f"gatherNode {gather.tile.toString()} value {gather.value}")
                totalValue += gather.value
                turns += gather.gatherTurns

            logbook.info(
                f"gather_to_target_tiles totalValue was {totalValue}. Setting gatherNodes for visual debugging regardless of using them")
            if totalValue > targetArmy - gatherTurns // 2:
                move = BotGatherOps.get_tree_move_default(bot, gatherNodes, valueFunc=leafMoveSelectionValueFunc)
                if move is not None:
                    bot.gatherNodes = gatherNodes
                    return BotRepetition.move_half_on_repetition(bot, move, 4), totalValue, turns, gatherNodes
                else:
                    logbook.info("Gather returned no moves :(")
            else:
                logbook.info(f"Value {totalValue} was too small to return... (needed {targetArmy}) :(")
        return None, -1, -1, None

    @staticmethod
    def get_gather_to_target_tiles_greedy(
            bot,
            targets,
            maxTime,
            gatherTurns,
            negativeSet=None,
            targetArmy=-1,
            useTrueValueGathered=False,
            priorityFunc=None,
            valueFunc=None,
            includeGatherTreeNodesThatGatherNegative=False,
            maximizeArmyGatheredPerTurn: bool = False,
            shouldLog: bool = False
    ) -> typing.Tuple[Move | None, int, int, typing.Union[None, typing.List[GatherTreeNode]]]:
        gatherNodes = Gather.greedy_backpack_gather(
            bot._map,
            targets,
            gatherTurns,
            targetArmy,
            negativeTiles=negativeSet,
            searchingPlayer=bot.general.player,
            viewInfo=bot.viewInfo,
            useTrueValueGathered=useTrueValueGathered,
            includeGatherTreeNodesThatGatherNegative=includeGatherTreeNodesThatGatherNegative,
            shouldLog=shouldLog)

        if maximizeArmyGatheredPerTurn:
            turns, value, gatherNodes = Gather.prune_mst_to_max_army_per_turn_with_values(
                gatherNodes,
                targetArmy,
                searchingPlayer=bot.general.player,
                teams=MapBase.get_teams_array(bot._map),
                preferPrune=bot.expansion_plan.preferred_tiles if bot.expansion_plan is not None else None,
                viewInfo=bot.viewInfo)

        totalValue = 0
        turns = 0
        for gather in gatherNodes:
            logbook.info(f"gatherNode {gather.tile.toString()} value {gather.value}")
            totalValue += gather.value
            turns += gather.gatherTurns

        logbook.info(
            f"gather_to_target_tiles totalValue was {totalValue}. Setting gatherNodes for visual debugging regardless of using them")
        if totalValue > targetArmy:
            move = BotGatherOps.get_tree_move_default(bot, gatherNodes, valueFunc=valueFunc)
            if move is not None:
                bot.gatherNodes = gatherNodes
                return BotRepetition.move_half_on_repetition(bot, move, 4), totalValue, turns, gatherNodes
            else:
                logbook.info("Gather returned no moves :(")
        else:
            logbook.info(f"Value {totalValue} was too small to return... (needed {targetArmy}) :(")
        return None, -1, -1, None

    @staticmethod
    def get_timing_gather_negatives_unioned(
            bot,
            gatherNegatives: typing.Set[Tile],
            additional_offset: int = 0,
            forceAllowCities: bool = False,
    ) -> typing.Set[Tile]:
        if not forceAllowCities:
            gatherNegatives = gatherNegatives.union(bot.cities_gathered_this_cycle)

        if BotStateQueries.is_all_in(bot):
            return gatherNegatives

        if BM.BotTargeting.BotTargeting.is_ffa_situation(bot) and bot.player.tileCount < 65:
            return gatherNegatives

        gatherNegatives.update(bot.win_condition_analyzer.defend_cities)

        if bot.currently_forcing_out_of_play_gathers or bot.defend_economy:
            return gatherNegatives

        if bot.gather_include_shortest_pathway_as_negatives:
            gatherNegatives = gatherNegatives.union(bot.board_analysis.intergeneral_analysis.shortestPathWay.tiles)

        armyCutoff = int(bot._map.players[bot.general.player].standingArmy ** 0.5)

        def foreach_func(tile: Tile):
            if tile in bot.tiles_gathered_to_this_cycle:
                return

            if not bot._map.is_tile_friendly(tile):
                return

            if tile.army > armyCutoff:
                return

            gatherNegatives.add(tile)

        if bot.gather_include_distance_from_enemy_general_as_negatives > 0:
            ratio = bot.gather_include_distance_from_enemy_general_large_map_as_negatives
            if bot.targetPlayerObj.tileCount < 150:
                ratio = bot.gather_include_distance_from_enemy_general_as_negatives
            excludeDist = int(bot.shortest_path_to_target_player.length * ratio)

            excludeDist += additional_offset

            SearchUtils.breadth_first_foreach(
                bot._map,
                [bot.targetPlayerExpectedGeneralLocation],
                maxDepth=excludeDist,
                foreachFunc=foreach_func,
            )

        if bot.gather_include_distance_from_enemy_TERRITORY_as_negatives > 0 and bot.targetPlayer != -1:
            excludeDist = bot.gather_include_distance_from_enemy_TERRITORY_as_negatives + additional_offset

            startTiles = [t for t in bot._map.get_all_tiles() if bot.territories.territoryMap[t] == bot.targetPlayer]

            SearchUtils.breadth_first_foreach(
                bot._map,
                startTiles,
                maxDepth=excludeDist,
                foreachFunc=foreach_func,
            )

        if bot.gather_include_distance_from_enemy_TILES_as_negatives > 0 and bot.targetPlayer != -1:
            excludeDist = bot.gather_include_distance_from_enemy_TILES_as_negatives

            startTiles = [t for t in bot._map.get_all_tiles() if t.player == bot.targetPlayer and not bot._map.is_player_on_team_with(bot.territories.territoryMap[t], bot.general.player)]

            if len(startTiles) > 0:
                SearchUtils.breadth_first_foreach(
                    bot._map,
                    startTiles,
                    maxDepth=excludeDist,
                    foreachFunc=foreach_func,
                )

        return gatherNegatives
