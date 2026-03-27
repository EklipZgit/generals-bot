import EarlyExpandUtils
import ExpandUtils
import DebugHelper
import random
import time
import typing

import SearchUtils
import logbook
from Behavior.ArmyInterceptor import InterceptionOptionInfo
from BehaviorAlgorithms.IterativeExpansion import ArmyFlowExpander
from Interfaces import TilePlanInterface
from MapMatrix import MapMatrix, MapMatrixInterface
from MoveListPath import MoveListPath
from Path import Path
from StrategyModels import ExpansionPotential
from Strategy.WinConditionAnalyzer import WinCondition
from Algorithms import WatchmanRouteUtils
from ViewInfo import TargetStyle, PathColorer
from base.client.map import Move, Tile


class BotExpansionOps:
    @staticmethod
    def get_optimal_city_or_general_plan_move(bot, timeLimit: float = 4.0) -> Move | None:
        calcedThisTurn = False
        if bot._map.turn < 50 and bot._map.is_2v2:
            bot.send_2v2_tip_to_ally()

        source = bot.general
        if len(bot.player.cities) > 0:
            sources = [bot.general]
            sources.extend(bot.player.cities)
            source = random.choice(sources)

        if bot._map.turn > 50:
            distMap = bot.get_expansion_weight_matrix(mult=10)
            skipTiles = set()
        else:
            distMap, skipTiles = bot.get_first_25_expansion_distance_priority_map()

        if bot.city_expand_plan is None or len(bot.city_expand_plan.plan_paths) == 0:
            with bot.perf_timer.begin_move_event('optimize_first_25'):
                calcedThisTurn = True
                cutoff = time.perf_counter() + timeLimit
                for tile in bot._map.get_all_tiles():
                    bot.viewInfo.bottomMidLeftGridText.raw[tile.tile_index] = f'dm{distMap.raw[tile.tile_index]:.2f}'
                bot.city_expand_plan = EarlyExpandUtils.optimize_first_25(bot._map, source, distMap, skipTiles=skipTiles, cutoff_time=cutoff, cramped=bot._spawn_cramped)

                totalTiles = bot.city_expand_plan.tile_captures + len(bot.player.tiles)
                if len(skipTiles) > 0 and totalTiles < 17 and bot._map.turn < 50:
                    bot.city_expand_plan = EarlyExpandUtils.optimize_first_25(bot._map, source, distMap, skipTiles=None, cutoff_time=cutoff, cramped=bot._spawn_cramped)

                while bot.city_expand_plan.plan_paths and bot.city_expand_plan.plan_paths[0] is None:
                    bot.city_expand_plan.plan_paths.pop(0)
                if bot._map.turn < 50:
                    bot.send_teammate_communication("I'm planning my start expand here, try to avoid these pinged tiles.", cooldown=50)

        if (
                (
                        bot.city_expand_plan.launch_turn > bot._map.turn
                        or (
                                bot.city_expand_plan.launch_turn < bot._map.turn
                                and not SearchUtils.any_where(
                                    bot.player.tiles,
                                    lambda tile: not tile.isGeneral and SearchUtils.any_where(tile.movable, lambda mv: not mv.isObstacle and tile.army - 1 > mv.army and not bot._map.is_tile_friendly(mv))
                                )
                        )
                )
                and not calcedThisTurn
        ):
            bot.city_expand_plan.tile_captures = EarlyExpandUtils.get_start_expand_captures(
                bot._map,
                bot.city_expand_plan.core_tile,
                bot.city_expand_plan.core_tile.army,
                bot._map.turn,
                bot.city_expand_plan.plan_paths,
                launchTurn=bot.city_expand_plan.launch_turn,
                noLog=False)

            distToGenMap = SearchUtils.build_distance_map_matrix(bot._map, bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=7)[0:3])

            with bot.perf_timer.begin_move_event(f're-check f25 (limit {timeLimit:.3f}'):
                cutoff = time.perf_counter() + timeLimit
                optionalNewExpandPlan = EarlyExpandUtils.optimize_first_25(bot._map, source, distMap, skipTiles=skipTiles, cutoff_time=cutoff, prune_cutoff=bot.city_expand_plan.tile_captures, shuffle_launches=True)
            if optionalNewExpandPlan is not None:
                visited = set(bot._map.players[bot.general.player].tiles)
                for teammate in bot._map.teammates:
                    visited.update(bot._map.players[teammate].tiles)
                visited.update(skipTiles)

                preRecalcCaps = bot.city_expand_plan.tile_captures
                maxPlan = EarlyExpandUtils.recalculate_max_plan(bot.city_expand_plan, optionalNewExpandPlan, bot._map, distToGenMap, distMap, visited, no_log=False)
                bot.viewInfo.add_info_line(f'Recalced a new f25, val {optionalNewExpandPlan.tile_captures} (vs post {bot.city_expand_plan.tile_captures} / pre {preRecalcCaps})')

                if maxPlan == optionalNewExpandPlan:
                    calcedThisTurn = True
                    bot.viewInfo.add_info_line(f'YOOOOO REPLACING OG F25 WITH NEW ONE, {optionalNewExpandPlan.tile_captures} >= {bot.city_expand_plan.tile_captures}')
                    bot.viewInfo.paths.clear()
                    bot.city_expand_plan = optionalNewExpandPlan

        r = 255
        g = 50
        a = 255
        for plan in bot.city_expand_plan.plan_paths:
            r -= 17
            r = max(0, r)
            a -= 10
            a = max(0, a)
            g += 10
            g = min(255, g)

            if plan is None:
                continue

            bot.viewInfo.color_path(
                PathColorer(plan.clone(), r, g, 50, alpha=a, alphaDecreaseRate=5, alphaMinimum=100))

        pingCooldown = 3
        if not bot.teamed_with_bot:
            pingCooldown = 8
        if bot.cooldown_allows("F25 PING COOLDOWN", pingCooldown):
            for plan in bot.city_expand_plan.plan_paths:
                if plan is None:
                    continue
                bot.send_teammate_path_ping(plan)

        if bot.city_expand_plan.launch_turn > bot._map.turn:
            bot.info(
                f"Expand plan ({bot.city_expand_plan.tile_captures}) isn't ready to launch yet, launch turn {bot.city_expand_plan.launch_turn}")
            return None

        if len(bot.city_expand_plan.plan_paths) > 0:
            countNone = 0
            for p in bot.city_expand_plan.plan_paths:
                if p is not None:
                    break
                countNone += 1

            if bot._map.turn == bot.city_expand_plan.launch_turn:
                while bot.city_expand_plan.plan_paths[0] is None:
                    bot.viewInfo.add_info_line(f'POPPING BAD EARLY DELAY OFF OF THE PLAN...?')
                    bot.city_expand_plan.plan_paths.pop(0)
            curPath = bot.city_expand_plan.plan_paths[0]
            if curPath is None:
                bot.info(
                    f'Expand plan {bot.city_expand_plan.tile_captures} no-opped until turn {countNone + bot._map.turn} :)')
                bot.city_expand_plan.plan_paths.pop(0)
                return None

            move = bot.get_first_path_move(curPath)
            bot.info(f'Expand plan {bot.city_expand_plan.tile_captures} path move {move}')

            collidedWithEnemyAndWastingArmy = move.source.player != move.dest.player and (move.dest.player != -1 or move.dest.isCity) and move.source.army - 1 <= move.dest.army or move.dest.player in bot._map.teammates
            if move.dest.isMountain:
                collidedWithEnemyAndWastingArmy = True
            if move.dest.isDesert and move.dest not in bot.city_expand_plan.intended_deserts:
                collidedWithEnemyAndWastingArmy = True

            if collidedWithEnemyAndWastingArmy and move.source.player == bot.general.player:
                collisionCapsOrPreventsEnemy = move.source.army == move.dest.army and move.source.army > 2 and move.dest.player not in bot._map.teammates
                if not collisionCapsOrPreventsEnemy:
                    newPath = bot.attempt_first_25_collision_reroute(curPath, move, distMap)
                    if newPath is None:
                        bMap = bot.board_analysis.intergeneral_analysis.bMap
                        bot.board_analysis.intergeneral_analysis.bMap = distMap
                        expansionNegatives = set()
                        if bot.teammate_general is not None:
                            expansionNegatives.update(bot._map.players[bot.teammate_general.player].tiles)
                        expansionNegatives.add(bot.general)
                        expUtilPlan = ExpandUtils.get_round_plan_with_expansion(
                            bot._map,
                            bot.general.player,
                            bot.targetPlayer,
                            50 - (bot._map.turn % 50),
                            bot.board_analysis,
                            bot.territories.territoryMap,
                            bot.tileIslandBuilder,
                            negativeTiles=expansionNegatives,
                            viewInfo=bot.viewInfo
                        )

                        path = expUtilPlan.selected_option
                        otherPaths = expUtilPlan.all_paths

                        bot.board_analysis.intergeneral_analysis.bMap = bMap

                        if path is not None:
                            bot.info(f'F25 Exp collided at {str(move.dest)}, falling back to EXP {str(path)}')

                            curPath.pop_first_move()
                            if curPath.length == 0:
                                bot.city_expand_plan.plan_paths.pop(0)

                            return bot.get_first_path_move(path)

                        bot.info(f'F25 Exp collided at {str(move.dest)}, no alternative found. No-opping')

                        curPath.pop_first_move()
                        if curPath.length == 0:
                            bot.city_expand_plan.plan_paths.pop(0)

                        return None

                    bot.viewInfo.add_info_line(
                        f'F25 Exp collided at {str(move.dest)}, capping {str(newPath)} instead.')
                    move = bot.get_first_path_move(newPath)
                    curPath = newPath
                else:
                    bot.info(
                        f'F25 Exp collided at {str(move.dest)}, continuing because collisionCapsOrPreventsEnemy.')

            curPath.pop_first_move()
            if curPath.length == 0:
                bot.city_expand_plan.plan_paths.pop(0)

            return move
        return None

    @staticmethod
    def try_find_main_timing_expansion_move_if_applicable(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if bot.is_all_in_losing:
            return None

        turnsLeft = bot.timings.get_turns_left_in_cycle(bot._map.turn)
        utilizationCutoff = turnsLeft - turnsLeft // 7
        value = bot.expansion_plan.en_tiles_captured * 2 + bot.expansion_plan.neut_tiles_captured
        haveFullExpPlanAlready = False
        if (
                bot.expansion_plan.turns_used >= turnsLeft - bot.player.cityCount * 2
                and bot.expansion_plan.en_tiles_captured > bot.expansion_plan.neut_tiles_captured // 3
                and bot.expansion_plan.en_tiles_captured * 2 + bot.expansion_plan.neut_tiles_captured > turnsLeft - 2
                and value > utilizationCutoff
                and bot._get_approximate_greedy_turns_available() > 0
        ):
            haveFullExpPlanAlready = True

        haveFullExpPlanAlready = False

        havePotentialIntercept = bot.expansion_plan.includes_intercept

        if haveFullExpPlanAlready or havePotentialIntercept or ((bot.curPath is None or bot.curPath.start is None or bot.curPath.start.next is None) and not bot.defend_economy or bot._map.turn < 100):
            expNegs = set(defenseCriticalTileSet)
            if not haveFullExpPlanAlready or bot.is_all_in():
                with bot.perf_timer.begin_move_event('checking launch move'):
                    attackLaunchMove = bot.check_for_attack_launch_move(expNegs)
                if attackLaunchMove is not None and not haveFullExpPlanAlready:
                    return attackLaunchMove

            with bot.perf_timer.begin_move_event("try_find_expansion_move main timing"):
                timeLimit = min(bot.get_remaining_move_time(), bot.expansion_full_time_limit)
                move = bot.try_find_expansion_move(expNegs, timeLimit, forceBypassLaunch=haveFullExpPlanAlready or havePotentialIntercept)

            if move is not None:
                if not bot.timings.in_expand_split(bot._map.turn) and haveFullExpPlanAlready:
                    cycleTurn = bot.timings.get_turn_in_cycle(bot._map.turn)
                    bot.viewInfo.add_info_line('Due to full expansion plan, moving down launch/gather split.')
                    bot.timings.launchTiming = max(20, cycleTurn)
                    bot.timings.splitTurns = cycleTurn
                return move

        return None

    @staticmethod
    def try_find_expansion_move(bot, defenseCriticalTileSet: typing.Set[Tile], timeLimit: float, forceBypassLaunch: bool = False, overrideTurns: int = -1) -> Move | None:
        skipForAllIn = bot.is_all_in_losing or bot.all_in_city_behind

        if not forceBypassLaunch and not bot.timings.in_expand_split(bot._map.turn) and overrideTurns < 0:
            return None

        if bot.targetPlayer != -1 and bot.is_still_ffa_and_non_dominant():
            if bot.opponent_tracker.winning_on_army(byRatio=1.1) and bot.opponent_tracker.winning_on_economy(byRatio=1.1) and bot.targetPlayerObj.aggression_factor > 30:
                bot.info("beating FFA player exp bypass")
                return None

            if bot.opponent_tracker.winning_on_army(byRatio=1.3, offset=-30):
                bot.info("crushing FFA player exp bypass")
                return None

        if bot.defend_economy:
            bot.viewInfo.add_info_line(
                f"skip exp bc self.defendEconomy ({bot.defend_economy})")
            return None

        if skipForAllIn:
            bot.viewInfo.add_info_line(
                f"skip exp bc self.all_in_counter ({bot.all_in_losing_counter}) / skipForAllIn {skipForAllIn} / is_all_in_army_advantage {bot.is_all_in_army_advantage}")
            return None

        expansionNegatives = defenseCriticalTileSet.copy()
        splitTurn = bot.timings.get_turn_in_cycle(bot._map.turn)
        if (not forceBypassLaunch and splitTurn < bot.timings.launchTiming and bot._map.turn > 50) or (bot.target_player_gather_path is not None and bot.target_player_gather_path.start.tile in expansionNegatives):
            bot.viewInfo.add_info_line(
                f"splitTurn {splitTurn} < launchTiming {bot.timings.launchTiming}...?")
            for tile in bot.target_player_gather_targets:
                if bot._map.is_tile_friendly(tile):
                    expansionNegatives.add(tile)

        tilesWithArmy = SearchUtils.where(
            bot._map.players[bot.general.player].tiles,
            filter_func=lambda t: (
                    (t.army > 2 or SearchUtils.any_where(t.movable, lambda mv: not bot._map.is_tile_friendly(mv) and t.army - 1 > mv.army))
                    and not t.isCity
                    and not t.isGeneral
            )
        )

        if (
                (
                        bot.city_expand_plan is not None
                        or (
                                len(tilesWithArmy) == 0
                        )
                )
                and (bot.expansion_plan is None or bot.expansion_plan.turns_used < bot.timings.get_turns_left_in_cycle(bot._map.turn))
                and not bot.is_still_ffa_and_non_dominant()
        ):
            remainingTime = bot.get_remaining_move_time()
            with bot.perf_timer.begin_move_event(f'EXP - first25 reuse - {remainingTime:.4f}'):
                move = bot.get_optimal_city_or_general_plan_move(timeLimit=remainingTime)
                if move is not None and (move.source.army == 1 or move.source.player != bot.general.player):
                    bot.city_expand_plan = None
                    bot.info(f'Aborting bad city_expand_plan reuse move {move}')
                else:
                    if bot._map.turn < bot.city_expand_plan.launch_turn:
                        bot.info(f'Optimal Expansion F25 piggyback wait {move}')
                        return None

                    bot.info(f'Optimal Expansion F25 piggyback {move}')

                    moveListPath = MoveListPath([])

                    for planPath in bot.city_expand_plan.plan_paths:
                        if planPath is None:
                            moveListPath.add_next_move(None)
                            continue
                        for m in planPath.get_move_list():
                            moveListPath.add_next_move(m)

                    bot.curPath = moveListPath
                    bot.city_expand_plan = None
                    return move

        bot._add_expansion_threat_negs(expansionNegatives)
        bot.expansion_plan = bot.build_expansion_plan(timeLimit, expansionNegatives, pathColor=(50, 30, 255), overrideTurns=overrideTurns)

        path = bot.expansion_plan.selected_option
        allPaths = bot.expansion_plan.all_paths

        expansionNegStr = " | ".join([str(t) for t in expansionNegatives])
        if path:
            pathMove = path.get_first_move()
            inLaunchSplit = bot.timings.in_launch_split(bot._map.turn)
            if pathMove.source.isGeneral and not inLaunchSplit and len(allPaths) > 1 and not bot.expansion_plan.includes_intercept:
                path = allPaths[1]

            move = path.get_first_move()
            if bot.is_all_in() and move.move_half:
                bot.viewInfo.add_info_line(f'because we\'re all in, will NOT move-half...')
                move.move_half = False
            if bot.is_move_safe_valid(move):
                bot.info(
                    f"EXP {path.econValue:.2f}/{path.length}t {move} neg ({expansionNegStr})")
                return move
            else:
                bot.info(
                    f"NOT SAFE EXP {path.econValue:.2f}/{path.length}t {move} neg ({expansionNegStr})")

        elif len(allPaths) > 0:
            bot.info(
                f"Exp had no paths, wait? neg {expansionNegStr}")
            return None
        else:
            bot.info(
                f"Exp move not found...? neg {expansionNegStr}")
        return None

    @staticmethod
    def build_expansion_plan(
            bot,
            timeLimit: float,
            expansionNegatives: typing.Set[Tile],
            pathColor: typing.Tuple[int, int, int],
            overrideTurns: int = -1,
            includeExtraGenAndCityArmy: bool = False
    ) -> ExpansionPotential:
        territoryMap = bot.territories.territoryMap

        numDanger = 0
        for tile in bot.general.movable:
            if (bot._map.is_tile_enemy(tile)
                    and tile.army > 5):
                numDanger += 1
                if tile.army > bot.general.army - 1:
                    numDanger += 1
        if numDanger > 1:
            expansionNegatives.add(bot.general)

        remainingCycleTurns = bot.timings.cycleTurns - bot.timings.get_turn_in_cycle(bot._map.turn)
        if overrideTurns > -1:
            remainingCycleTurns = overrideTurns

        if bot.city_expand_plan is not None and len(bot.city_expand_plan.plan_paths) == 0:
            bot.city_expand_plan = None

        with bot.perf_timer.begin_move_event(f'optimal_expansion'):
            bonusCapturePointMatrix = bot.get_expansion_weight_matrix()

            remainingMoveTime = bot.get_remaining_move_time()
            if remainingMoveTime < timeLimit and not DebugHelper.IS_DEBUGGING:
                timeLimit = remainingMoveTime
                if remainingMoveTime < 0.05:
                    timeLimit = 0.05

            if bot.teammate_general is not None:
                expansionNegatives.add(bot.teammate_general)

                for army in bot.armyTracker.armies.values():
                    if army.player in bot._map.teammates and army.last_moved_turn > bot._map.turn - 3:
                        expansionNegatives.add(army.tile)

                if bot.threat is not None and bot.threat.turns < 2 and bot.threat.path.tail.tile == bot.general:
                    expansionNegatives.add(bot.general)

            interceptOptionsSet: typing.Set[TilePlanInterface] = set()
            addlOptions: typing.List[TilePlanInterface] = []
            for threatTile, interceptPlan in bot.intercept_plans.items():
                for turns, option in interceptPlan.intercept_options.items():
                    addlOptions.append(option)
                    interceptOptionsSet.add(option)

                    logbook.info(f'intOpt {str(option)}')

            if bot.expansion_use_iterative_flow:
                with bot.perf_timer.begin_move_event('FLOW EXPAND!'):
                    ogStart = time.perf_counter()
                    flowExpander = ArmyFlowExpander(bot._map)

                    cutoffTime = time.perf_counter()
                    if bot.expansion_use_legacy:
                        cutoffTime += 1 * timeLimit / 2
                    else:
                        cutoffTime += timeLimit

                    flowExpander.friendlyGeneral = bot.general
                    flowExpander.enemyGeneral = bot.targetPlayerExpectedGeneralLocation
                    flowExpander.debug_render_capture_count_threshold = 10000
                    flowExpander.log_debug = False
                    flowExpander.use_debug_asserts = False

                    optCollection = flowExpander.get_expansion_options(
                        islands=bot.tileIslandBuilder,
                        asPlayer=bot.player.index,
                        targetPlayer=bot.targetPlayer,
                        turns=remainingCycleTurns,
                        boardAnalysis=bot.board_analysis,
                        territoryMap=bot.territories.territoryMap,
                        negativeTiles=expansionNegatives,
                        cutoffTime=cutoffTime,
                    )

                    addlOptions.extend(optCollection.flow_plans)

                    timeLimit = timeLimit - (time.perf_counter() - ogStart)

            islands = bot.tileIslandBuilder
            expUtilPlan = ExpandUtils.get_round_plan_with_expansion(
                bot._map,
                searchingPlayer=bot.player.index,
                targetPlayer=bot.targetPlayer,
                turns=remainingCycleTurns,
                boardAnalysis=bot.board_analysis,
                territoryMap=territoryMap,
                tileIslands=islands,
                negativeTiles=expansionNegatives,
                leafMoves=bot.captureLeafMoves,
                useLeafMovesFirst=bot.expansion_use_leaf_moves_first,
                viewInfo=bot.viewInfo,
                includeExpansionSearch=bot.expansion_use_legacy,
                singleIterationPathTimeCap=min(bot.expansion_single_iteration_time_cap, timeLimit / 3),
                forceNoGlobalVisited=bot.expansion_force_no_global_visited,
                forceGlobalVisitedStage1=bot.expansion_force_global_visited_stage_1,
                useIterativeNegTiles=bot._should_use_iterative_negative_expand(),
                allowLeafMoves=bot.expansion_allow_leaf_moves,
                allowGatherPlanExtension=bot.expansion_allow_gather_plan_extension,
                alwaysIncludeNonTerminatingLeavesInIteration=bot.expansion_always_include_non_terminating_leafmoves_in_iteration,
                time_limit=timeLimit,
                lengthWeightOffset=bot.expansion_length_weight_offset,
                useCutoff=bot.expansion_use_cutoff,
                threatBlockingTiles=bot.blocking_tile_info,
                colors=pathColor,
                smallTileExpansionTimeRatio=bot.expansion_small_tile_time_ratio,
                bonusCapturePointMatrix=bonusCapturePointMatrix,
                additionalOptionValues=addlOptions,
                includeExtraGenAndCityArmy=includeExtraGenAndCityArmy,
                perfTimer=bot.perf_timer)

            path = expUtilPlan.selected_option
            otherPaths = expUtilPlan.all_paths

            bot.viewInfo.add_stats_line(f'EXP AVAIL {expUtilPlan.turns_used} {expUtilPlan.cumulative_econ_value:.2f} - (en{expUtilPlan.en_tiles_captured} neut{expUtilPlan.neut_tiles_captured})')

        plan = ExpansionPotential(
            expUtilPlan.turns_used,
            expUtilPlan.en_tiles_captured,
            expUtilPlan.neut_tiles_captured,
            path,
            otherPaths,
            expUtilPlan.cumulative_econ_value
        )

        anyIntercept = isinstance(plan.selected_option, InterceptionOptionInfo)
        interceptVtCutoff = 1.99
        if remainingCycleTurns > 35:
            interceptVtCutoff = 2.6
        elif remainingCycleTurns > 28:
            interceptVtCutoff = 2.3
        elif remainingCycleTurns > 22:
            interceptVtCutoff = 2.2

        if len(addlOptions) > 0:
            for otherPath in plan.all_paths:
                if otherPath in interceptOptionsSet:
                    for planOpt in bot.intercept_plans.values():
                        interceptOption = planOpt.get_intercept_option_by_path(otherPath)
                        if interceptOption is not None:
                            isOneMoveLargeIntercept = interceptOption.length < 2 or otherPath.length == 1
                            if isOneMoveLargeIntercept or interceptOption.econValue / interceptOption.length > interceptVtCutoff:
                                bot.viewInfo.add_info_line(f'EXP USED INT {interceptOption} ({interceptOption.path})')
                                if interceptOption.requiredDelay > 0:
                                    logbook.info(f'    HAD DELAY {interceptOption}')
                                    plan.blocking_tiles.update(interceptOption.tileSet)
                                    plan.intercept_waiting.append(interceptOption)
                                else:
                                    plan.includes_intercept = True
                                    anyIntercept = True
                                    plan.selected_option = otherPath
                                    break

                i = 0
                for t in otherPath.tileSet:
                    planOpt = bot.intercept_plans.get(t, None)
                    if planOpt is not None:
                        intPath = None
                        for turns, option in planOpt.intercept_options.items():
                            if option == planOpt:
                                bot.info(f'THIS SHOULD NOT HAPPEN, option == planOpt {planOpt}')
                                bot.info(f'THIS SHOULD NOT HAPPEN, option == planOpt {planOpt}')
                                bot.info(f'THIS SHOULD NOT HAPPEN, option == planOpt {planOpt}')
                                bot.info(f'THIS SHOULD NOT HAPPEN, option == planOpt {planOpt}')
                                bot.info(f'THIS SHOULD NOT HAPPEN, option == planOpt {planOpt}')
                                bot.info(f'THIS SHOULD NOT HAPPEN, option == planOpt {planOpt}')
                                continue
                            econValue = option.econValue
                            p = option.path
                            isOneMoveLargeIntercept = p.length == 1 or turns < 2
                            if p.start.tile == otherPath.get_first_move().source and (isOneMoveLargeIntercept or econValue / turns > interceptVtCutoff):
                                bot.viewInfo.add_info_line(f'EXP INDIR INT ON {str(t)} W {str(otherPath)}')

                                if option.requiredDelay > 0:
                                    bot.viewInfo.add_info_line(f'   HAD DELAY {option}')
                                    plan.blocking_tiles.update(option.tileSet)
                                    plan.intercept_waiting.append(option)
                                else:
                                    plan.includes_intercept = True
                                    bot.viewInfo.add_info_line(f'   REPLACING WITH {option} ({option.path})')
                                    anyIntercept = True
                                    plan.selected_option = option
                                    plan.all_paths[plan.all_paths.index(otherPath)] = option
                                    break

                        if anyIntercept:
                            plan.includes_intercept = True
                            break

                        i += 1

                if anyIntercept:
                    break

            if not anyIntercept:
                bot.viewInfo.add_info_line(f'no exp intercept.. despite {len(addlOptions)} opts?')

        if not anyIntercept:
            plan = bot.check_launch_against_expansion_plan(plan, expansionNegatives)

        for path in plan.all_paths:
            plan.preferred_tiles.update(path.tileSet)

        return plan

    @staticmethod
    def build_enemy_expansion_plan(
            bot,
            timeLimit: float,
            pathColor: typing.Tuple[int, int, int]
    ) -> ExpansionPotential:
        if bot.targetPlayer == -1 or not bot.armyTracker.seen_player_lookup[bot.targetPlayer]:
            return ExpansionPotential(0, 0, 0, None, [], 0.0)

        territoryMap = bot.territories.territoryMap

        remainingCycleTurns = bot.timings.cycleTurns - bot.timings.get_turn_in_cycle(bot._map.turn)

        with bot.perf_timer.begin_move_event(f'enemy optimal_expansion'):
            remainingMoveTime = bot.get_remaining_move_time()
            if remainingMoveTime < timeLimit and not DebugHelper.IS_DEBUGGING:
                timeLimit = remainingMoveTime
                if remainingMoveTime < 0.02:
                    timeLimit = 0.02

            enFrTiles = bot._map.get_teammates(bot.targetPlayer)
            negativeTiles = set()
            for tile in bot._map.reachable_tiles:
                if not tile.discovered and tile.player in enFrTiles and tile not in bot.armyTracker.armies:
                    negativeTiles.add(tile)

            oldA = bot.board_analysis.intergeneral_analysis.aMap
            oldB = bot.board_analysis.intergeneral_analysis.bMap

            bot.board_analysis.intergeneral_analysis.aMap = oldB
            bot.board_analysis.intergeneral_analysis.bMap = oldA
            if DebugHelper.IS_DEBUGGING:
                timeLimit *= 4
            try:
                expUtilPlan = ExpandUtils.get_round_plan_with_expansion(
                    bot._map,
                    searchingPlayer=bot.targetPlayer,
                    targetPlayer=bot.player.index,
                    turns=remainingCycleTurns,
                    boardAnalysis=bot.board_analysis,
                    territoryMap=territoryMap,
                    tileIslands=bot.tileIslandBuilder,
                    negativeTiles=negativeTiles,
                    leafMoves=bot.targetPlayerLeafMoves,
                    useLeafMovesFirst=bot.expansion_use_leaf_moves_first,
                    viewInfo=bot.viewInfo,
                    singleIterationPathTimeCap=min(bot.expansion_single_iteration_time_cap, timeLimit / 3),
                    forceNoGlobalVisited=bot.expansion_force_no_global_visited,
                    forceGlobalVisitedStage1=bot.expansion_force_global_visited_stage_1,
                    useIterativeNegTiles=bot._should_use_iterative_negative_expand(),
                    allowLeafMoves=bot.expansion_allow_leaf_moves,
                    allowGatherPlanExtension=bot.expansion_allow_gather_plan_extension,
                    alwaysIncludeNonTerminatingLeavesInIteration=bot.expansion_always_include_non_terminating_leafmoves_in_iteration,
                    time_limit=timeLimit,
                    lengthWeightOffset=bot.expansion_length_weight_offset,
                    useCutoff=bot.expansion_use_cutoff,
                    smallTileExpansionTimeRatio=bot.expansion_small_tile_time_ratio,
                    threatBlockingTiles=bot.blocking_tile_info,
                    colors=pathColor,
                    bonusCapturePointMatrix=None)
            finally:
                bot.board_analysis.intergeneral_analysis.aMap = oldA
                bot.board_analysis.intergeneral_analysis.bMap = oldB

            path = expUtilPlan.selected_option
            otherPaths = expUtilPlan.all_paths

            bot.enemy_expansion_plan_tile_path_cap_values = {}

            if path is not None:
                otherPaths.insert(0, path)

            for otherPath in otherPaths:
                army = bot.armyTracker.armies.get(otherPath.get_first_move().source, None)
                if isinstance(otherPath, Path):
                    if army is not None:
                        army.include_path(otherPath)

            bot.viewInfo.add_stats_line(f'EN EXP AVAIL {expUtilPlan.turns_used} {expUtilPlan.cumulative_econ_value:.2f} - (fr{expUtilPlan.en_tiles_captured} neut{expUtilPlan.neut_tiles_captured})')

        plan = ExpansionPotential(
            expUtilPlan.turns_used,
            expUtilPlan.en_tiles_captured,
            expUtilPlan.neut_tiles_captured,
            path,
            otherPaths,
            expUtilPlan.cumulative_econ_value
        )

        return plan

    @staticmethod
    def attempt_first_25_collision_reroute(
            bot,
            curPath: Path,
            move: Move,
            distMap: MapMatrixInterface[int]
    ) -> Path | None:
        countExtraUseableMoves = 0
        for path in bot.city_expand_plan.plan_paths:
            if path is None:
                countExtraUseableMoves += 1

        negExpandTiles = set()
        negExpandTiles.add(bot.general)
        if bot.teammate_general is not None:
            negExpandTiles.update(bot._map.players[bot.teammate_general.player].tiles)

        lengthToReplaceCurrentPlan = curPath.length
        rePlanLength = lengthToReplaceCurrentPlan + countExtraUseableMoves
        with bot.perf_timer.begin_move_event(f'Re-calc F25 Expansion for {str(move.source)} (length {rePlanLength})'):
            expUtilPlan = ExpandUtils.get_round_plan_with_expansion(
                bot._map,
                bot.general.player,
                bot.targetPlayer,
                rePlanLength,
                bot.board_analysis,
                bot.territories.territoryMap,
                bonusCapturePointMatrix=bot.get_expansion_weight_matrix(),
                tileIslands=bot.tileIslandBuilder,
                negativeTiles=negExpandTiles,
                viewInfo=bot.viewInfo
            )
        newPath = expUtilPlan.selected_option
        otherPaths = expUtilPlan.all_paths

        _, _, _, pathTurns, econVal, remainingArmy, _ = bot.calculate_path_capture_econ_values(curPath, 50)

        if newPath is not None and isinstance(newPath, Path):
            _, _, _, newTurns, newEconVal, newRemainingArmy, _ = bot.calculate_path_capture_econ_values(newPath, 50)
            if newEconVal <= econVal:
                bot.info(f'recalc attempt found {newPath} with econ {newEconVal:.2f} (vs collisions {econVal:.2f}), will not reroute...')
                return None
            segments = newPath.break_overflow_into_one_move_path_subsegments(
                lengthToKeepInOnePath=lengthToReplaceCurrentPlan)
            bot.city_expand_plan.plan_paths[0] = None
            if segments[0] is not None:
                for i in range(segments[0].length, lengthToReplaceCurrentPlan):
                    logbook.info(f'plan segment 0 {str(segments[0])} was shorter than lengthToReplaceCurrentPlan {lengthToReplaceCurrentPlan}, inserting a None')
                    bot.city_expand_plan.plan_paths.insert(0, None)

            curSegIndex = 0
            for i in range(len(bot.city_expand_plan.plan_paths)):
                if bot.city_expand_plan.plan_paths[i] is None and curSegIndex < len(segments):
                    if i > 0:
                        logbook.info(f'Awesome, managed to replace expansion no-ops with expansion in F25 collision!')
                    bot.city_expand_plan.plan_paths[i] = segments[curSegIndex]
                    curSegIndex += 1

            return segments[0]
        else:
            return None

    @staticmethod
    def find_leaf_move(bot, allLeaves):
        leafMoves = bot.prioritize_expansion_leaves(allLeaves)
        if bot.target_player_gather_path is not None:
            leafMoves = list(SearchUtils.where(leafMoves, lambda move: move.source not in bot.target_player_gather_path.tileSet))
        if len(leafMoves) > 0:
            move = leafMoves[0]
            i = 0
            valid = True
            while move.source.isGeneral and not bot.general_move_safe(move.dest):
                if bot.general_move_safe(move.dest, True):
                    move.move_half = True
                    break
                else:
                    move = random.choice(leafMoves)
                    i += 1
                    if i > 10:
                        valid = False
                        break

            if valid:
                bot.curPath = None
                bot.curPathPrio = -1
                return move
        return None

    @staticmethod
    def prioritize_expansion_leaves(
            bot,
            allLeaves=None,
            allowNonKill=False,
            distPriorityMap: MapMatrixInterface[int] | None = None,
    ) -> typing.List[Move]:
        queue = SearchUtils.HeapQueue()
        analysis = bot.board_analysis.intergeneral_analysis

        expansionMap = bot.get_expansion_weight_matrix()

        if distPriorityMap is None:
            distPriorityMap = analysis.bMap

        for leafMove in allLeaves:
            if not allowNonKill and leafMove.source.army - leafMove.dest.army <= 1:
                continue
            if not allowNonKill and (leafMove.dest.isDesert or leafMove.dest.isSwamp):
                continue
            if leafMove.source.army < 2:
                continue
            if bot._map.is_tile_friendly(leafMove.dest):
                continue
            if leafMove.dest.isCity and leafMove.dest.player == -1 and leafMove.dest.army > 25:
                continue

            dest = leafMove.dest
            source = leafMove.source
            if (
                    bot.territories.territoryMap[dest] != -1
                    and not bot._map.is_player_on_team_with(bot.territories.territoryMap[dest], bot.general.player)
                    and dest.player == -1
                    and bot._map.turn % 50 < 45
            ):
                continue

            points = 0

            if bot.board_analysis.innerChokes[dest]:
                points += 0.1
            if not bot.board_analysis.outerChokes[dest]:
                points += 0.05

            if bot.board_analysis.intergeneral_analysis.is_choke(dest):
                points += 0.15

            towardsEnemy = distPriorityMap[dest] < distPriorityMap[source]
            if towardsEnemy:
                points += 0.4

            awayFromUs = analysis.aMap[dest] > analysis.aMap[source]
            if awayFromUs:
                points += 0.1

            if dest.player == bot.targetPlayer:
                points += 1.5

            points += expansionMap[dest] * 5

            distEnemyPoints = (analysis.aMap[dest] + 1) / (distPriorityMap[dest] + 1)

            points += distEnemyPoints / 3

            logbook.info(f"leafMove {leafMove}, points {points:.2f} (distEnemyPoints {distEnemyPoints:.2f})")
            queue.put((0 - points, leafMove))
        vals = []
        while queue.queue:
            prio, move = queue.get()
            vals.append(move)
        return vals

    @staticmethod
    def timing_expand(bot):
        turnOffset = bot._map.turn + bot.timings.offsetTurns
        turnCycleOffset = turnOffset % bot.timings.cycleTurns
        if turnCycleOffset >= bot.timings.splitTurns:
            return None
        return None

    @staticmethod
    def make_first_25_move(bot) -> Move | None:
        timeLimit = bot.get_remaining_move_time()

        for city in bot.cityAnalyzer.city_scores.keys():
            if city.army < 30:
                return bot.try_find_expansion_move(set(), 0.15)

        if bot.city_expand_plan is not None and timeLimit > 0:
            used = bot.perf_timer.get_elapsed_since_update(bot._map.turn)
            moveCycleTime = 0.5
            latencyBuffer = 0.22
            allowedLatest = moveCycleTime - latencyBuffer
            timeLimit = allowedLatest - used
            i = 0
            while bot._map.turn + i < 12:
                i += 1
                timeLimit += moveCycleTime - 0.1
            if DebugHelper.IS_DEBUGGING:
                timeLimit = max(timeLimit, 0.1)
            bot.viewInfo.add_info_line(f'Allowing f25 time limit {timeLimit:.3f}')
            timeLimit = min(2.0, timeLimit)
        elif bot._map.turn < 7:
            timeLimit = 3.75
            if bot._map.is_2v2:
                if bot.city_expand_plan is None:
                    if bot.teamed_with_bot:
                        timeLimit = 0.75
                    else:
                        timeLimit = 2.75
                else:
                    timeLimit = 1.75

            if bot._map.cols * bot._map.rows > 1000 or len(bot._map.players) > 8:
                timeLimit = 0.75
        move = bot.get_optimal_city_or_general_plan_move(timeLimit=timeLimit)
        if move is not None:
            if move.source.player == bot.general.player:
                return move
        return None

    @staticmethod
    def get_optimal_exploration(
            bot,
            turns,
            negativeTiles: typing.Set[Tile] = None,
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

        toReveal = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=0, player=bot.targetPlayer, cutoffEmergenceRatio=emergenceRatio, includeCities=includeCities)
        targetArmyLevel = bot.determine_fog_defense_amount_available_for_tiles(toReveal, bot.targetPlayer)

        for t in toReveal:
            bot.mark_tile(t, alpha=50)

        if len(toReveal) == 0:
            return None

        startArmies = sorted(bot.get_largest_tiles_as_armies(bot.general.player, limit=3), key=lambda t: bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, t.tile))

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
                maxTime = bot.get_remaining_move_time() / 2

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
    def explore_target_player_undiscovered(bot, negativeTiles: typing.Set[Tile] | None, onlyHuntGeneral: bool | None = None, maxTime: float | None = None) -> Path | None:
        if negativeTiles:
            negativeTiles = negativeTiles.copy()
        if bot._map.turn < 50 or bot.targetPlayer == -1:
            return None

        turnInCycle = bot.timings.get_turn_in_cycle(bot._map.turn)
        exploringUnknown = bot._map.generals[bot.targetPlayer] is None

        genPlayer = bot._map.players[bot.general.player]
        behindOnCities = genPlayer.cityCount < bot._map.players[bot.targetPlayer].cityCount

        if not bot.is_all_in():
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
        if bot.is_all_in() and not bot.is_all_in_army_advantage and not bot.all_in_city_behind:
            turns = 15
            minArmy = int(genPlayer.standingArmy ** 0.83) - 10
            bot.info(f"Forcing explore to t{turns} and minArmy to {minArmy} because self.is_all_in()")
        elif turns < 6:
            logbook.info(f"Forcing explore turns to minimum of 5, was {turns}")
            turns = 5
        elif turnInCycle < 6 and exploringUnknown:
            logbook.info(f"Forcing explore turns to minimum of 6, was {turns}")
            turns = 6

        if bot._map.turn < 100:
            return None

        path = bot.get_optimal_exploration(turns, negativeTiles, minArmy=minArmy, maxTime=maxTime)
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
    def check_launch_against_expansion_plan(bot, existingPlan: ExpansionPotential, expansionNegatives: typing.Set[Tile]) -> ExpansionPotential:
        if bot.target_player_gather_path is None:
            return existingPlan

        launchPath = bot.get_path_subsegment_starting_from_last_move(bot.target_player_gather_path)

        if launchPath is None or launchPath.start is None:
            return existingPlan

        if launchPath.start.tile in expansionNegatives:
            bot.viewInfo.add_info_line(f'---EXP Launch (negs)')
            return existingPlan

        turnsLeftInCycle = bot.timings.get_turns_left_in_cycle(bot._map.turn)

        if launchPath.length > turnsLeftInCycle:
            launchPath = launchPath.get_subsegment(turnsLeftInCycle)

        distToFirstFogTile, enCaps, neutCaps, turns, econVal, remainingArmy, fullFriendlyArmy = bot.calculate_path_capture_econ_values(launchPath, turnsLeftInCycle)

        if turns == 0:
            bot.viewInfo.add_info_line(f'---EXP Launch (t0 {str(launchPath.start.tile)}) (en{enCaps} neut{neutCaps}) vs existing (en{existingPlan.en_tiles_captured} neut{existingPlan.neut_tiles_captured})')
            return existingPlan

        if bot.targetPlayer != -1 and bot.armyTracker.seen_player_lookup[bot.targetPlayer] and ((enCaps <= 0 and neutCaps <= 0) or econVal <= 0):
            bot.viewInfo.add_info_line(f'---EXP Launch (useless) (en{enCaps} neut{neutCaps}) vs existing (en{existingPlan.en_tiles_captured} neut{existingPlan.neut_tiles_captured})')
            return existingPlan

        if launchPath.start.tile.player != bot.general.player:
            bot.viewInfo.add_info_line(f'---EXP Launch not our player')
            return existingPlan

        if launchPath.start.tile.army < 7 or launchPath.start.tile.army < fullFriendlyArmy / 5 + 1:
            bot.viewInfo.add_info_line(f'---EXP Launch (lowval {str(launchPath.start.tile)}) (en{enCaps} neut{neutCaps}) vs existing (en{existingPlan.en_tiles_captured} neut{existingPlan.neut_tiles_captured})')
            return existingPlan

        existingExpandPlanVal = 0
        if existingPlan is not None:
            existingExpandPlanVal = existingPlan.cumulative_econ_value

        playerTiles = bot.opponent_tracker.get_player_fog_tile_count_dict(bot.targetPlayer)
        worstCappable = 0
        if len(playerTiles) > 0:
            worstCappable = max(playerTiles.keys())
        probableRemainingCaps = min(turnsLeftInCycle - launchPath.length, remainingArmy // (worstCappable + 1))
        launchTurnsTotal = turns + probableRemainingCaps

        if launchTurnsTotal == 0:
            return existingPlan

        factor = 2
        if bot.targetPlayer == -1 or len(bot.targetPlayerObj.tiles) == 0:
            factor = 1

        launchVal = econVal + probableRemainingCaps * factor

        launchValPerTurn = launchVal / launchTurnsTotal

        existingValPerTurn = existingExpandPlanVal / turnsLeftInCycle
        if existingPlan.turns_used > turnsLeftInCycle - 10:
            existingValPerTurn = existingExpandPlanVal / max(1, existingPlan.turns_used)

        existingPlanForTile = next(iter(p for p in existingPlan.all_paths if p.tileList[0] == launchPath.start.tile), None)
        if existingPlanForTile is not None:
            tilePlanVt = existingPlanForTile.econValue / existingPlanForTile.length
            bot.info(f'EXP Launch replacing full {existingValPerTurn:.3f} to ts {tilePlanVt:.3f}')
            existingValPerTurn = tilePlanVt

        if launchValPerTurn > existingValPerTurn and (launchTurnsTotal > turnsLeftInCycle - 5 or distToFirstFogTile < bot.target_player_gather_path.length // 2 - 1):
            launchSubsegment = launchPath.get_subsegment(distToFirstFogTile)

            launchSubsegmentToEn = bot.get_path_subsegment_to_closest_enemy_team_territory(launchSubsegment)
            if launchSubsegmentToEn is None:
                launchSubsegmentToEn = launchSubsegment

            paths = existingPlan.all_paths.copy()
            interceptFake = InterceptionOptionInfo(
                launchSubsegmentToEn,
                econVal,
                launchSubsegment.length + probableRemainingCaps,
                damageBlocked=0,
                interceptingArmyRemaining=0,
                bestCaseInterceptMoves=0,
                worstCaseInterceptMoves=0,
                recaptureTurns=probableRemainingCaps,
                requiredDelay=0,
                friendlyArmyReachingIntercept=0)
            paths.insert(0, interceptFake)
            bot.viewInfo.add_info_line(f'EXP Launch vt{launchValPerTurn:.2f} (en{enCaps} neut{neutCaps}) vs existing {existingValPerTurn:.2f} (en{existingPlan.en_tiles_captured} neut{existingPlan.neut_tiles_captured})')
            newPlan = ExpansionPotential(
                turnsUsed=existingPlan.turns_used + launchTurnsTotal,
                enTilesCaptured=enCaps,
                neutTilesCaptured=neutCaps,
                selectedOption=interceptFake,
                allOptions=paths,
                cumulativeEconVal=existingPlan.cumulative_econ_value + launchVal
            )

            return newPlan

        bot.viewInfo.add_info_line(f'---EXP Launch vt{launchValPerTurn:.2f} (en{enCaps} neut{neutCaps}) vs existing {existingValPerTurn:.2f} (en{existingPlan.en_tiles_captured} neut{existingPlan.neut_tiles_captured})')

        return existingPlan

    @staticmethod
    def calculate_path_capture_econ_values(bot, launchPath, turnsLeftInCycle, negativeTiles: typing.Set[Tile] | None = None) -> typing.Tuple[int, int, int, int, int, int, int]:
        econMatrix = bot.get_expansion_weight_matrix()

        army = 0
        turns = -1
        enCaps = 0
        neutCaps = 0
        distToFirstCap = -1
        distToFirstFogTile = -1
        friendlyArmy = 0
        econVal = 0
        for tile in launchPath.tileList:
            turns += 1
            isFriendly = bot._map.is_tile_friendly(tile)
            if isFriendly:
                army += tile.army - 1
                friendlyArmy += tile.army - 1
            else:
                army -= tile.army + 1

                if distToFirstFogTile == -1 and not tile.visible:
                    distToFirstFogTile = turns

                if army < 0:
                    break

                if distToFirstCap == -1:
                    distToFirstCap = turns

                econVal += econMatrix.raw[tile.tile_index]

                if tile.isSwamp:
                    army -= 1
                    econVal -= 1
                elif not tile.isDesert:
                    if bot._map.is_player_on_team_with(bot.targetPlayer, tile.player):
                        enCaps += 1
                    else:
                        neutCaps += 1

            if army <= 0:
                break
            if turns >= turnsLeftInCycle:
                break

        if distToFirstCap == -1:
            distToFirstCap = launchPath.length
        if distToFirstFogTile == -1:
            distToFirstFogTile = launchPath.length

        econVal += 2 * enCaps + neutCaps

        return distToFirstFogTile, enCaps, neutCaps, turns, econVal, army, friendlyArmy

    @staticmethod
    def make_second_25_move(bot) -> Move | None:
        if bot._map.turn >= 100 or bot.is_ffa_situation() or bot.completed_first_100 or bot._map.is_2v2 or bot.targetPlayer == -1:
            return None

        foundEnemy = SearchUtils.any_where(bot.targetPlayerObj.tiles, lambda t: t.visible)

        cutoff = 67
        if foundEnemy:
            cutoff = 67

        if bot._map.turn > cutoff:
            return None

        if bot.curPath is not None:
            if bot.curPath.start.tile.army - 1 > bot.curPath.start.next.tile.army:
                return bot.continue_cur_path(threat=None, defenseCriticalTileSet=set())

            bot.curPath = None

        expMap = bot.get_expansion_weight_matrix()

        leafMoves = [m for m in bot.leafMoves if m.source.army > 1]
        enDists = bot._alt_en_gen_position_distances[bot.targetPlayer]
        leafMovesClosestToGen = list(sorted(leafMoves, key=lambda m: bot.distance_from_general(m.dest)))
        leafMoves = leafMovesClosestToGen[7:]
        if len(leafMoves) > 0:
            return leafMoves[-1]

        tilePathLookup = {}
        for p in bot.expansion_plan.all_paths:
            tilePathLookup[p.tileList[0]] = p
        maxPath: Path | None = None
        possibleGenTargets = bot.alt_en_gen_positions[bot.targetPlayer]
        enDists = bot._alt_en_gen_position_distances[bot.targetPlayer]
        mustGather = set(bot.player.tiles)
        mustGatherTo = set(bot.target_player_gather_path.tileList)
        for tile in bot.target_player_gather_path.tileList:
            mustGather.discard(tile)

        negTiles = set()

        bypass = set()

        def foreachFunc(tile: Tile) -> bool:
            if tile.tile_index in bypass or enDists.raw[tile.tile_index] > enDists.raw[bot.general.tile_index] + 1:
                return True

            anyMovable = False
            bestMv = None
            bestMvDist = 1000
            for t in tile.movable:
                if not t.isObstacle and bot._map.team_ids_by_player_index[t.player] != bot._map.team_ids_by_player_index[bot.general.player] and enDists.raw[t.tile_index] <= enDists.raw[tile.tile_index]:
                    if bestMvDist > enDists.raw[t.tile_index]:
                        bestMvDist = enDists.raw[t.tile_index]
                        bestMv = t
                    anyMovable = True
                    break

            if anyMovable and tile.player == bot.general.player:
                mustGatherTo.add(bestMv)
                logbook.info(f'INCL {tile}->{bestMv}')

                def foreachSkipNearby(nearbyTile: Tile) -> bool:
                    if nearbyTile.player != bot.general.player:
                        return True
                    bypass.add(nearbyTile.tile_index)

                SearchUtils.breadth_first_foreach_fast_no_neut_cities(bot._map, [tile], 5, foreachSkipNearby)

        SearchUtils.breadth_first_foreach_fast_no_neut_cities(
            bot._map,
            bot.alt_en_gen_positions[bot.targetPlayer],
            maxDepth=150,
            foreachFunc=foreachFunc,
        )

        for tile in bot.player.tiles:
            if tile.army == 1:
                mustGather.discard(tile)

        for tile in bot.target_player_gather_path.tileList:
            mustGather.discard(tile)
            if not bot._map.is_tile_friendly(tile):
                mustGatherTo.discard(tile)

        for move in leafMoves:
            mustGather.discard(move.source)

        for tile in mustGatherTo:
            bot.viewInfo.add_targeted_tile(tile, TargetStyle.GREEN, radiusReduction=8)

        gatherTieBreaks = bot.get_gather_tiebreak_matrix()
        for tile in mustGather:
            gatherTieBreaks.raw[tile.tile_index] += 0.5
            bot.viewInfo.add_targeted_tile(tile, TargetStyle.YELLOW, radiusReduction=8)

        gathTurns = len(mustGather)

        gathTargets = {}
        for tile in mustGatherTo:
            path = tilePathLookup.get(tile, None)
            if path is None:
                gathTargets[tile] = 0
                continue

            allowedAddlArmy = path.length - tile.army + 1

            depth = gathTurns - allowedAddlArmy
            logbook.info(f'setting {str(tile)} to depth {depth} / {gathTurns} (army {tile.army}, path len {path.length}, allowedAddlArmy {allowedAddlArmy})')
            gathTargets[tile] = depth

        move, valGathered, gathTurns, gatherNodes = bot.get_gather_to_target_tiles(
            gathTargets,
            0.1,
            gatherTurns=gathTurns,
            priorityMatrix=gatherTieBreaks
        )

        if bot.timings.splitTurns - bot._map.cycleTurn < gathTurns:
            newSplit = bot._map.cycleTurn + gathTurns
            bot.info(f'increasing gather duration from {bot.timings.splitTurns} to {newSplit}')
            bot.timings.splitTurns = newSplit
            if bot.timings.launchTiming < bot.timings.splitTurns:
                bot.timings.launchTiming = bot.timings.splitTurns

        if move is not None:
            if move.source in bot.out_of_play_tiles or enDists.raw[move.source.tile_index] > enDists.raw[bot.general.tile_index]:
                bot.info(f'f50 out of play {move}')
                return move

        if gatherNodes:
            sendPath: Path | None = None
            expansionPathsByStartTile = {}
            for p in bot.expansion_plan.all_paths:
                expansionPathsByStartTile[p.tileList[0]] = p

            for node in gatherNodes:
                if node.gatherTurns == 0 and node.tile not in bot.target_player_gather_path.tileSet:
                    path = expansionPathsByStartTile.get(node.tile, None)
                    if path:
                        bot.curPath = path
                        bot.info(f'f50 0 node path {str(path)}')
                        return bot.get_first_path_move(path)

        for tile in possibleGenTargets:
            bot.viewInfo.add_targeted_tile(tile, TargetStyle.RED, radiusReduction=8)

        if maxPath is not None:
            useMaxPath = True
            if gatherNodes:
                maxPathNodes = SearchUtils.where(gatherNodes, lambda n: n.tile == maxPath.start.tile)
                if len(maxPathNodes) > 0:
                    gathNode = maxPathNodes[0]
                    if gathNode.gatherTurns != 0:
                        useMaxPath = False
            if useMaxPath:
                bot.curPath = maxPath
                bot.info(f'f50 maxpath {str(maxPath)}')
                return bot.get_first_path_move(maxPath)

        if gatherNodes:
            bot.gatherNodes = gatherNodes
            move = bot.get_tree_move_default(gatherNodes)
            if move is not None:
                bot.info(f'f50 Expansion gather {move}')
                return move

        bot.completed_first_100 = True

        return None

    @staticmethod
    def check_army_out_of_play_ratio(bot) -> bool:
        """
        0.0 means all army is in the core play area
        1.0 means all army is outside the core play area.
        0.5 means hella sketchy, half our army is outside the play area.
        @return:
        """
        bot.out_of_play_tiles = set()
        if bot.force_far_gathers and bot.force_far_gathers_turns <= 0:
            bot.force_far_gathers_turns = 0
            bot.force_far_gathers_sleep_turns = 50
            bot.force_far_gathers = False

        if bot._map.is_2v2 and bot.teammate_general is not None:
            return False

        if bot._map.turn < 100 and not bot.is_weird_custom:
            return False

        if bot.targetPlayer == -1 or bot.shortest_path_to_target_player is None:
            return False

        inPlaySum = 0
        medPlaySum = 0
        outOfPlaySum = 0
        outOfPlayCount = 0
        nearOppSum = 0
        genPlayer = bot._map.players[bot.general.player]
        pathLen = bot.shortest_path_to_target_player.length
        inPlayCutoff = pathLen + pathLen * (bot.behavior_out_of_play_distance_over_shortest_ratio / 2)
        mediumRangeCutoff = pathLen + pathLen * bot.behavior_out_of_play_distance_over_shortest_ratio

        outOfPlayTiles = bot.out_of_play_tiles
        for tile in genPlayer.tiles:
            genDist = bot.board_analysis.intergeneral_analysis.aMap.raw[tile.tile_index]
            enDist = bot.board_analysis.intergeneral_analysis.bMap.raw[tile.tile_index]
            if genDist > enDist * 2:
                nearOppSum += tile.army - 1
                continue
            if tile.isGeneral:
                continue

            pathWay = bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix.raw[tile.tile_index]
            if pathWay is None:
                bot.viewInfo.add_info_line(f'tile {str(tile)} had no pathway...? genDist{genDist} enDist{enDist}')

            if pathWay is not None and pathWay.distance <= inPlayCutoff:
                inPlaySum += tile.army - 1
            elif pathWay is not None and pathWay.distance < mediumRangeCutoff:
                medPlaySum += tile.army - 1
            else:
                outOfPlaySum += tile.army - 1
                outOfPlayCount += 1
                outOfPlayTiles.add(tile)

        total = medPlaySum + inPlaySum + outOfPlaySum + nearOppSum
        if total == 0:
            return False

        hugeGameOffset = 0
        realTotal = total
        incMedium = medPlaySum // 2
        if total > 90:
            hugeGameOffset = int((total - 90) ** 0.8)
            total = 90 + hugeGameOffset
            incMedium = 0

        inPlayRat = inPlaySum / total
        medPlayRat = medPlaySum / total
        outOfPlaySumFactored = outOfPlaySum - nearOppSum // 3 + incMedium
        outOfPlayRat = outOfPlaySumFactored / total

        aboveOutOfPlay = outOfPlayRat > bot.behavior_out_of_play_defense_threshold

        tilesMinusDeserts = bot.player.tileCount - len(bot.player.deserts)
        if outOfPlayRat > 1.4 and (tilesMinusDeserts > 150 or bot.player.cityCount > 5 or len(bot.defensive_spanning_tree) > 50):
            if bot.force_far_gathers_sleep_turns <= 0 and not bot.force_far_gathers:
                bot.force_far_gathers = True
                bot.force_far_gathers_turns = bot._map.remainingCycleTurns
                minTurns = max(tilesMinusDeserts // 2, len(bot.defensive_spanning_tree) + outOfPlayCount // 2, outOfPlayCount) + bot.board_analysis.inter_general_distance * outOfPlayRat
                while bot.force_far_gathers_turns <= minTurns:
                    bot.force_far_gathers_turns += 50
                cap = outOfPlayCount
                if bot.target_player_gather_path:
                    cap += int(bot.target_player_gather_path.length / 2)
                if bot.force_far_gathers_turns > cap:
                    bot.force_far_gathers_turns = cap

        bot.viewInfo.add_stats_line(
            f'out-of-play {outOfPlayRat:.2f} {aboveOutOfPlay} {total:.0f}@dist{mediumRangeCutoff:.1f}: OUT{outOfPlaySum}-OPP{nearOppSum}+MF{incMedium} ({outOfPlayRat:.2f}>{bot.behavior_out_of_play_defense_threshold:.2f}), IN{inPlaySum}({inPlayRat:.2f}), MED{medPlaySum}({medPlayRat:.2f}), Tot{total} ogTot{realTotal} (huge {hugeGameOffset}, inCut {inPlayCutoff:.1f}, medCut {mediumRangeCutoff:.1f})')

        return aboveOutOfPlay

    @staticmethod
    def _should_use_iterative_negative_expand(bot) -> bool:
        if bot._map.turn < 150:
            return False
        return bot.expansion_use_iterative_negative_tiles

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
                (bot.is_all_in() or bot.finishing_exploration or demolishingTargetPlayer)
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
                path = bot.get_quick_kill_on_enemy_cities(defenseCriticalTileSet)
                if path is not None:
                    bot.info(f'ALL IN ARMY ADVANTAGE CITY CONTEST {str(path)}')
                    return bot.get_first_path_move(path)

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
                path = bot.explore_target_player_undiscovered(undiscNeg, maxTime=timeCap)
                if path is not None:
                    bot.viewInfo.color_path(PathColorer(path, 120, 150, 127, 200, 12, 100))
                    if not bot.is_path_moving_mostly_away(path, bot.board_analysis.intergeneral_analysis.bMap):
                        valueSubsegment = bot.get_value_per_turn_subsegment(path, minLengthFactor=0)
                        if valueSubsegment.length != path.length:
                            logbook.info(f"BAD explore_target_player_undiscovered")
                            bot.info(
                                f"WHOAH, tried to make a bad exploration path...? Fixed with {str(valueSubsegment)}")
                            path = valueSubsegment
                        move = bot.get_first_path_move(path)
                        if not bot.detect_repetition(move, 7, 2):
                            if bot.is_all_in_army_advantage:
                                bot.all_in_army_advantage_counter -= 2
                            return move
                        else:
                            bot.info('bypassed hunting due to repetitions.')
                    else:
                        bot.info(f'IGNORING BAD HUNTING PATH BECAUSE MOVES AWAY FROM GEN APPROX')

        return None

    @staticmethod
    def _add_expansion_threat_negs(bot, negs: typing.Set[Tile]):
        logbook.info(f'starting expansion threat negs: {[t for t in negs]}')
        if bot.threat is None:
            return

        if bot.threat.threatType == ThreatType.Kill:
            turn = bot._map.turn
            for tile in bot.threat.path.tileList:
                if turn % 50 == 0 and turn != bot._map.turn:
                    break
                turn += 1
                if bot._map.team_ids_by_player_index[tile.player] != bot._map.team_ids_by_player_index[bot.general.player] or bot.threat.threatValue > 0:
                    if tile not in negs:
                        logbook.info(f"  Added neg {tile}, turn {turn}")
                        negs.add(tile)

        bot.army_interceptor.ensure_threat_army_analysis(bot.threat)

    @staticmethod
    def get_first_25_expansion_distance_priority_map(bot) -> typing.Tuple[MapMatrixInterface[int], typing.Set[Tile]]:
        """
        Returns a matrix of big-number=bad expansion priorities, and skip tiles (if teams).
        Safe to be modified.

        @return:
        """

        if bot.is_ffa_situation():
            return bot._get_avoid_other_players_expansion_matrix(), set()

        numberStartTargets = 2

        if bot.targetPlayer != -1:
            tgs, enDistMap = bot._get_furthest_apart_3_enemy_general_locations(bot.targetPlayer)
        else:
            tgs = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=12)[0:numberStartTargets]

            if len(tgs) < numberStartTargets:
                tgs = bot.get_target_player_possible_general_location_tiles_sorted(elimNearbyRange=8)[0:numberStartTargets]

            for tg in tgs:
                bot.viewInfo.add_targeted_tile(tg, TargetStyle.TEAL)

            enDistMap = SearchUtils.build_distance_map_matrix(bot._map, tgs)

        distSource = []
        skipTiles = set()

        if bot._map.is_2v2 and bot.teammate_general is not None:
            if bot._map.turn < 46:
                expandPlanSizeIndicated = len(bot.tiles_pinged_by_teammate_this_turn) + len(bot._map.players[bot.teammate_general.player].tiles)
                if len(bot.tiles_pinged_by_teammate_this_turn) > 3 and expandPlanSizeIndicated > 18:
                    bot.viewInfo.add_info_line(f'reset team f25, received teammate tile pings indicative of full expansion plan')
                    bot._tiles_pinged_by_teammate_first_25 = set()

                for t in bot.tiles_pinged_by_teammate_this_turn:
                    bot._tiles_pinged_by_teammate_first_25.add(t)

            if bot._map.turn > 12 or not bot.teammate_communicator.is_team_lead or not bot.teammate_communicator.is_teammate_coordinated_bot:
                skipTiles = bot._tiles_pinged_by_teammate_first_25.copy()

            distMap = MapMatrix(bot._map, 0)

            usDist = bot._map.distance_mapper.get_tile_dist_matrix(bot.general)

            for tile in bot._map.get_all_tiles():
                distMap[tile] += enDistMap[tile]
                distMap[tile] -= usDist[tile] // 2
                distMap[tile] += bot.get_distance_from_board_center(tile, center_ratio=0.75)

            teammateDistanceDropoffPoint = 9
            for teammate in bot._map.teammates:
                teammateDistances = SearchUtils.build_distance_map_matrix(bot._map, [bot._map.generals[teammate]])
                for otherTile in bot._map.get_all_tiles():
                    if teammateDistances[otherTile] < usDist[otherTile]:
                        distMap[otherTile] += 3 * teammateDistanceDropoffPoint - 3 * teammateDistances[otherTile]

            if len(skipTiles) == 0:
                if not bot._spawn_cramped:
                    teammateAnalysis = ArmyAnalyzer(bot._map, bot.general, bot.teammate_general)
                    for tile in teammateAnalysis.shortestPathWay.tiles:
                        if tile == bot.general:
                            continue
                        if teammateAnalysis.aMap[tile] > teammateAnalysis.bMap[tile] or (teammateAnalysis.aMap[tile] == teammateAnalysis.bMap[tile] and not bot.teammate_communicator.is_team_lead):
                            logbook.info(f' adding f25 skiptile {tile} due to proximity to ally gen')
                            skipTiles.add(tile)
                else:
                    skipTiles.update(bot.teammate_general.movable)

        elif bot._map.remainingPlayers == 2:
            distSource.append(bot.general)
            distMap = SearchUtils.build_distance_map_matrix(bot._map, distSource)
            for tile in bot._map.get_all_tiles():
                distMap[tile] = 0 - distMap[tile]
                distMap[tile] += enDistMap[tile]
                distMap[tile] += bot.get_distance_from_board_center(tile, center_ratio=0.85)
        elif bot._map.remainingPlayers > 2:
            distSource.append(bot.general)
            distMap = SearchUtils.build_distance_map_matrix(bot._map, distSource)

            for tile in bot._map.get_all_tiles():
                distMap[tile] -= bot.get_distance_from_board_center(tile, center_ratio=0.15)
        else:
            raise AssertionError("The fuck?")

        for tile in bot._map.get_all_tiles():
            if isinstance(distMap[tile], float):
                bot.viewInfo.midLeftGridText[tile] = f'f{distMap[tile]:.1f}'
            else:
                bot.viewInfo.midLeftGridText[tile] = f'f{str(distMap[tile])}'
            if tile in skipTiles:
                bot.viewInfo.add_targeted_tile(tile, TargetStyle.RED, radiusReduction=6)

        return distMap, skipTiles

    @staticmethod
    def get_expansion_weight_matrix(bot, copy: bool = False, mult: int = 1) -> MapMatrixInterface[float]:
        if bot._expansion_value_matrix is None:
            logbook.info(f'rebuilding expansion weight matrix for turn {bot._map.turn}')
            if bot.is_still_ffa_and_non_dominant():
                bot._expansion_value_matrix = bot._get_avoid_other_players_expansion_matrix()
            else:
                bot._expansion_value_matrix = bot._get_standard_expansion_capture_weight_matrix()

        if mult != 1:
            copyMat = bot._expansion_value_matrix.copy()
            for t in bot._map.get_all_tiles():
                copyMat.raw[t.tile_index] *= mult

            return copyMat

        if copy:
            return bot._expansion_value_matrix.copy()

        return bot._expansion_value_matrix

    @staticmethod
    def look_for_ffa_turtle_move(bot) -> Move | None:
        """

        @return:
        """
        haveSeenOtherPlayer: bool = False
        neutCity: Tile | None = None
        nearEdgeOfMap: bool = bot.get_distance_from_board_center(bot.general, center_ratio=0.25) > 5

        if not neutCity or haveSeenOtherPlayer:
            return None

        remainingCycleTurns = 50 - bot._map.turn % 50
        potentialGenBonus = remainingCycleTurns // 2
        sumArmy = bot.sum_player_army_near_tile(neutCity, distance=100, player=bot.general.player)
        if sumArmy + potentialGenBonus - 3 > neutCity.army:
            path, move = bot.capture_cities(negativeTiles=set(), forceNeutralCapture=True)
            if move is not None:
                bot.info(f'AM I NOT TURTLEY ENOUGH FOR THE TURTLE CLUB? {move}')
                return move
            if path is not None:
                bot.info(f'AM I NOT TURTLEY ENOUGH FOR THE TURTLE CLUB? {str(path)}')
                return bot.get_first_path_move(path)

        return None

    @staticmethod
    def try_gather_tendrils_towards_enemy(bot, turns: int | None = None) -> Move | None:
        return None

    @staticmethod
    def try_get_enemy_territory_exploration_continuation_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if bot.targetPlayer == -1:
            return None

        if bot.is_all_in():
            path = bot.explore_target_player_undiscovered(defenseCriticalTileSet, onlyHuntGeneral=True)
            if path is not None:
                bot.info(f'all-in exploration move...? {str(path)}')
                return bot.get_first_path_move(path)
            return None

        if bot.timings.get_turns_left_in_cycle(bot._map.turn) < 15:
            return None

        if bot.armyTracker.has_perfect_information_of_player_cities_and_general(bot.targetPlayer):
            return None

        armyCutoff = 4 + 4 * int(bot.player.standingArmy / bot.player.tileCount)
        if bot.defend_economy:
            armyCutoff *= 2
            armyCutoff += 10

        logbook.info(f'EN TERRITORY CONT EXP, armyCutoff {armyCutoff}')
        move = bot._get_expansion_plan_exploration_move(armyCutoff, defenseCriticalTileSet)

        if move is not None:
            bot.try_find_expansion_move(defenseCriticalTileSet, timeLimit=bot.get_remaining_move_time())
            move = bot._get_expansion_plan_exploration_move(armyCutoff, defenseCriticalTileSet)
            if move is not None:
                bot.info(f'EN TERRITORY CONT EXP! {move} - armyCutoff {armyCutoff}')
                return move

        return None

    @staticmethod
    def _get_expansion_plan_exploration_move(bot, armyCutoff: int, negativeTiles: typing.Set[Tile]) -> Move | None:
        move = None
        maxPath: TilePlanInterface | None = None
        if bot.expansion_plan is None:
            return None
        for path in bot.expansion_plan.all_paths:
            if path.get_first_move().source.army < armyCutoff:
                continue

            containsFogCount = 0
            skip = False
            for tile in path.tileSet:
                if tile in negativeTiles:
                    skip = True
                    break
                distanceFromGen = bot.distance_from_general(tile)
                if distanceFromGen < 7 or (bot.territories.territoryDistances[bot.targetPlayer][tile] > 2 and not bot.armyTracker.valid_general_positions_by_player[bot.targetPlayer][tile]):
                    skip = True
                    break
                for adj in tile.adjacents:
                    if not adj.discovered:
                        containsFogCount += 1

            if skip or containsFogCount < path.length:
                continue

            if maxPath is None or maxPath.get_first_move().source.army < path.get_first_move().source.army:
                maxPath = path

        if maxPath is not None:
            move = maxPath.get_first_move()

        return move

    @staticmethod
    def _get_expansion_plan_quick_capture_move(bot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if not bot.behavior_allow_pre_gather_greedy_leaves:
            return None

        if bot.currently_forcing_out_of_play_gathers:
            return None

        if (
                (bot._map.remainingPlayers != 2 and not bot._map.is_2v2)
                or bot.opponent_tracker.winning_on_economy(byRatio=1.35, cityValue=4, offset=bot.behavior_pre_gather_greedy_leaves_offset)
                or bot.approximate_greedy_turns_avail <= 0
        ):
            return None

        negativeTiles = defenseCriticalTileSet.copy()
        if not bot.timings.in_launch_timing(bot._map.turn):
            negativeTiles.update(bot.target_player_gather_path.tileList)

        move = None
        maxPath: TilePlanInterface | None = None

        highValueSet = set()

        def does_tile_capture_expand_our_vision(tile: Tile) -> bool:
            if bot.board_analysis.flankable_fog_area_matrix[tile]:
                return True

            for movable in tile.movable:
                if bot.board_analysis.flankable_fog_area_matrix[movable]:
                    return True

            return False

        for tile in bot._map.reachable_tiles:
            if bot._map.is_tile_on_team_with(tile, bot.targetPlayer):
                highValueSet.add(tile)
                continue

            if does_tile_capture_expand_our_vision(tile):
                highValueSet.add(tile)
                continue

        maxScoreVt = -1
        for path in bot.expansion_plan.all_paths:
            if highValueSet.isdisjoint(path.tileSet):
                continue

            if not negativeTiles.isdisjoint(path.tileSet):
                continue

            if path.length > bot.approximate_greedy_turns_avail:
                continue

            if SearchUtils.any_where(path.tileList, lambda t: t.army == 1 and bot._map.is_tile_friendly(t)):
                continue

            scoreVt = path.econValue / path.length
            if maxPath is None or maxScoreVt < scoreVt:
                maxPath = path
                maxScoreVt = scoreVt

        if maxPath is not None and maxScoreVt > 1.0:
            move = maxPath.get_first_move()
            if bot.timings.in_gather_split(bot._map.turn) and bot.timings.splitTurns < bot.timings.launchTiming:
                bot.timings.splitTurns += 1
                bot.info(f'greedy exp move {move} (vt {maxScoreVt:.2f}), inc gather {bot.timings.splitTurns - 1}->{bot.timings.splitTurns}')
            else:
                bot.info(f'greedy exp move {move} (vt {maxScoreVt:.2f})')

        return move

    @staticmethod
    def _get_avoid_other_players_expansion_matrix(bot) -> MapMatrixInterface[float]:
        matrix = MapMatrix(bot._map, 0.0)
        for tile in bot._map.get_all_tiles():
            if bot.targetPlayer != -1 and (tile.player == bot.targetPlayer or bot.territories.territoryMap[tile] == bot.targetPlayer):
                if tile in bot.board_analysis.intergeneral_analysis.shortestPathWay.tiles:
                    continue

            if tile.player != -1:
                matrix[tile] -= 0.6

            for adj in tile.adjacents:
                if not adj.discovered and not adj.isObstacle:
                    matrix[tile] -= 0.1
                if bot.targetPlayer != -1 and (adj.player == bot.targetPlayer or bot.territories.territoryMap[adj] == bot.targetPlayer):
                    matrix[tile] = 0.0
                    break
            if bot.info_render_expansion_matrix_values:
                val = matrix[tile]
                if val:
                    bot.viewInfo.bottomLeftGridText[tile] = f'hx{val:0.3f}'

        return matrix

    @staticmethod
    def get_unexpandable_ratio(bot) -> float:
        fromTiles = bot._map.players[bot.general.player].tiles
        distance = 8

        nearby = []

        def tile_finder(tile: Tile, dist: int) -> bool:
            isFriendly = bot._map.is_tile_friendly(tile)
            if tile.isCity and not isFriendly and tile.army > 0:
                return True
            if not isFriendly:
                nearby.append(tile)
            return False

        SearchUtils.breadth_first_foreach_dist_fast_incl_neut_cities(bot._map, fromTiles, distance, foreachFunc=tile_finder)

        if not nearby:
            bot.info(f'No tiles nearby...?')
            return 1.0

        if len(nearby) < bot._map.remainingCycleTurns:
            expResRaw = (bot._map.remainingCycleTurns - len(nearby)) / bot._map.remainingCycleTurns
            weightedExpRes = 0.4 + expResRaw
            bot.info(f'No expandability? expResRaw {expResRaw:.3f}, weightedExpRes {weightedExpRes:.3f}')
            return weightedExpRes

        numSwamp = SearchUtils.count(nearby, lambda t: t.isSwamp)
        numDesert = SearchUtils.count(nearby, lambda t: t.isDesert)
        numVisible = SearchUtils.count(nearby, lambda t: t.visible)
        ratioBad = numSwamp / len(nearby)
        ratioBad += numDesert / max(1, numVisible)

        if ratioBad > 0.6:
            bot.info(f'surrounded by unexpandables. ratioBad {ratioBad:.3f}, total nearby {len(nearby)}, numSwamp {numSwamp}, totalVisible {numVisible}, numDesert {numDesert}')
            return ratioBad
        bot.info(f'Not fully surrounded by unexpandables. ratioBad {ratioBad:.3f}, total nearby {len(nearby)}, numSwamp {numSwamp}, totalVisible {numVisible}, numDesert {numDesert}')

        return ratioBad

    @staticmethod
    def _get_standard_expansion_capture_weight_matrix(bot) -> MapMatrixInterface[float]:
        matrix = MapMatrix(bot._map, 0.0)

        innerChokes = bot.board_analysis.innerChokes

        dontRevealCities = bot.targetPlayer != -1 and bot.opponent_tracker.winning_on_economy(byRatio=1.05) and not bot.opponent_tracker.winning_on_army(byRatio=1.10)

        numEnGenPos = len(bot.alt_en_gen_positions[bot.targetPlayer])
        enPotentialGenDistances = bot._alt_en_gen_position_distances[bot.targetPlayer]
        genPosesToConsider = bot.alt_en_gen_positions[bot.targetPlayer]

        searchingForFirstContact = False
        if bot.targetPlayer != -1 and not bot.armyTracker.seen_player_lookup[bot.targetPlayer]:
            searchingForFirstContact = True

        if numEnGenPos > 6:
            bot.info(f'filtering down valid general set')
            avgDist = sum(bot.board_analysis.intergeneral_analysis.aMap.raw[t.tile_index] for t in genPosesToConsider) / len(genPosesToConsider)
            genPosesToConsider = [t for t in genPosesToConsider if bot.board_analysis.intergeneral_analysis.aMap.raw[t.tile_index] >= avgDist]
            for pos in genPosesToConsider:
                bot.viewInfo.add_targeted_tile(pos, targetStyle=TargetStyle.GREEN, radiusReduction=8)
            numEnGenPos = len(genPosesToConsider)
            enPotentialGenDistances = None

        if enPotentialGenDistances is None:
            enPotentialGenDistances = SearchUtils.build_distance_map_matrix(bot._map, genPosesToConsider)
            bot._alt_en_gen_position_distances[bot.targetPlayer] = enPotentialGenDistances
        tgPlayerTerritoryDists = bot.territories.territoryDistances[bot.targetPlayer]

        if dontRevealCities:
            bot.viewInfo.add_info_line(f'!@! expansion avoiding revealing cities')
            for city in bot.win_condition_analyzer.defend_cities:
                cityDist = bot.territories.territoryDistances[bot.targetPlayer][city]
                for tile in city.movable:
                    if tile.isNeutral and tgPlayerTerritoryDists.raw[tile.tile_index] < cityDist:
                        bot.viewInfo.add_targeted_tile(tile, targetStyle=TargetStyle.PURPLE, radiusReduction=12)
                        matrix.raw[tile.tile_index] -= 100

        if bot.enemy_attack_path is not None:
            for tile in bot.enemy_attack_path.tileList:
                if not tile.visible and tile not in bot.target_player_gather_path.tileSet:
                    matrix.raw[tile.tile_index] += 0.2

        if bot.sketchiest_potential_inbound_flank_path is not None and bot.targetPlayerObj and len(bot.targetPlayerObj.tiles) > 0:
            cutoff = 2 * bot.board_analysis.inter_general_distance // 5

            for tile in bot.sketchiest_potential_inbound_flank_path.adjacentSet:
                if bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, tile) < cutoff:
                    continue

                if not tile.visible:
                    matrix.raw[tile.tile_index] += 0.1
                else:
                    matrix.raw[tile.tile_index] += 0.03

            for tile in bot.sketchiest_potential_inbound_flank_path.tileSet:
                if bot._map.get_distance_between(bot.targetPlayerExpectedGeneralLocation, tile) < cutoff:
                    continue
                if not tile.visible:
                    matrix.raw[tile.tile_index] += 0.15
                else:
                    matrix.raw[tile.tile_index] += 0.03

        endOfCyclePenaltyRatio = 35 / (bot._map.cycleTurn + 5)
        if searchingForFirstContact:
            endOfCyclePenaltyRatio = 0
        bot.info(f'enemy expansion endOfCyclePenaltyRatio {endOfCyclePenaltyRatio:.3f}')

        for tile, scoreData in bot.cityAnalyzer.get_sorted_neutral_scores()[0:2]:
            if scoreData.general_distances_ratio < 1.1:
                for adj in tile.adjacents:
                    if bot._map.is_tile_enemy(adj):
                        matrix.raw[adj.tile_index] += 0.5

                    if adj.isNeutral and not adj.isUndiscoveredObstacle and scoreData.general_distances_ratio > 0.6:
                        matrix.raw[adj.tile_index] += max(0.0, 0.05 * (scoreData.general_distances_ratio - 0.1))
                        if not adj.discovered:
                            matrix.raw[adj.tile_index] += max(0.0, 0.05 * (scoreData.general_distances_ratio - 0.1))

        if bot.enemy_expansion_plan is not None:
            for enPath in bot.enemy_expansion_plan.all_paths:
                for tile in enPath.tileList[1:]:
                    if bot._map.is_tile_friendly(tile):
                        matrix.raw[tile.tile_index] -= bot.expansion_enemy_expansion_plan_inbound_penalty * endOfCyclePenaltyRatio

        for lookout in bot._map.lookouts:
            for tile in lookout.movableNoObstacles:
                if (bot.targetPlayer == -1 and not bot._map.is_tile_friendly(tile)) or (bot.targetPlayer >= 0 and bot._map.is_tile_on_team_with(tile, bot.targetPlayer)):
                    matrix.raw[tile.tile_index] += 0.5
                elif tile.player == -1:
                    matrix.raw[tile.tile_index] += 0.25

        for observatory in bot._map.observatories:
            for tile in observatory.movableNoObstacles:
                if (bot.targetPlayer == -1 and not bot._map.is_tile_friendly(tile)) or (bot.targetPlayer >= 0 and bot._map.is_tile_on_team_with(tile, bot.targetPlayer)):
                    matrix.raw[tile.tile_index] += 0.5
                elif tile.player == -1:
                    matrix.raw[tile.tile_index] += 0.25

        for tile in bot._map.get_all_tiles():
            bonus = 0.0
            if innerChokes.raw[tile.tile_index]:
                bonus += 0.002

            enDist = enPotentialGenDistances.raw[tile.tile_index]
            genDist = bot._map.get_distance_between(bot.general, tile)

            isCloserToEn = enDist < genDist * 0.9
            enDistRatio = (genDist + 3) / max(1, (enDist + numEnGenPos // 3))

            enExpVal = bot.enemy_expansion_plan_tile_path_cap_values.get(tile, None)
            if enExpVal is not None:
                bonus += enExpVal / 2

            if bot.board_analysis.intergeneral_analysis.is_choke(tile):
                bonus += 0.01

            isNeutral = tile.isNeutral
            isFriendly = not isNeutral and bot._map.is_tile_friendly(tile)
            isTarget = not isNeutral and bot._map.is_player_on_team_with(tile.player, bot.targetPlayer)

            if isFriendly and tile.army < 2:
                bonus -= 0.2

            if tile.isSwamp:
                if isTarget:
                    bonus -= 4.0
                elif isNeutral:
                    bonus -= 2.0

            if tile.isDesert:
                if isTarget:
                    bonus -= 2.0
                elif isNeutral:
                    bonus -= 1.0

            anyFlankVis = False
            for vis in tile.adjacents:
                if vis in bot.board_analysis.flankable_fog_area_matrix:
                    anyFlankVis = True
                    break

            if anyFlankVis:
                bonus += 0.05

            if tile.player == -1 and tgPlayerTerritoryDists.raw[tile.tile_index] < 3:
                bonus += 0.03

            if tile.isCity:
                cityScore = bot.cityAnalyzer.city_scores.get(tile, None)
                isCityGapping = (cityScore is None or cityScore.intergeneral_distance_differential > 0) and not bot._map.is_tile_friendly(tile)
                for vis in tile.adjacents:
                    if vis.isNotPathable or bot._map.is_tile_friendly(vis):
                        continue
                    if isCloserToEn or not isCityGapping or enPotentialGenDistances.raw[tile.tile_index] <= enPotentialGenDistances.raw[vis.tile_index]:
                        matrix.raw[vis.tile_index] += 0.05

            if isTarget:
                if tile.army > 1:
                    bonus += 0.02 + min(50, tile.army) * 0.02

            if not tile.discovered and bot.armyTracker.valid_general_positions_by_player[bot.targetPlayer].raw[tile.tile_index] and numEnGenPos < 10:
                bonus -= 0.01

            if bot._map.is_tile_on_team_with(tile, bot.targetPlayer) and bot.territories.is_tile_in_friendly_territory(tile):
                bonus += 0.05

            libertyCount = 0
            for mv in tile.movable:
                if not mv.isObstacle and not (mv.isNeutral and mv.army > 1):
                    libertyCount += 1
            if libertyCount == 1:
                bonus += 0.1
                if isTarget:
                    bonus += 0.3

            pathway = bot.board_analysis.intergeneral_analysis.pathWayLookupMatrix.raw[tile.tile_index]
            if pathway is not None:
                extendedDist = pathway.distance - bot.board_analysis.within_extended_play_area_threshold
                outsideExtendedPlay = extendedDist > 0
                if outsideExtendedPlay and not (tile in bot.board_analysis.flank_danger_play_area_matrix and SearchUtils.any_where(pathway.tiles, lambda t: not t.visible and t in bot.board_analysis.flankable_fog_area_matrix)):
                    isEnTile = bot._map.is_player_on_team_with(bot.targetPlayer, tile.player)
                    if isEnTile:
                        factor = 0.5
                        if not tile.discovered:
                            factor = 0.2
                        bonus -= factor / max(4, 15 - extendedDist)
                    else:
                        bonus -= 1.0 / max(4, 15 - extendedDist)
            else:
                bonus -= 10

            if bot._map.remainingCycleTurns > 8 and not searchingForFirstContact:
                cappedRat = max(1.1, enDistRatio)
                if tile.player == -1:
                    bonus += 0.1 - 0.05 * cappedRat
                else:
                    bonus += 0.06 - 0.03 * cappedRat

            excessDist = enPotentialGenDistances.raw[tile.tile_index] - bot.board_analysis.inter_general_distance - numEnGenPos
            if excessDist > 0:
                bonus -= 0.10 * excessDist / max(2, len(genPosesToConsider))

            if bot._map.is_tile_friendly(tile):
                if tile.army < 2:
                    bonus -= -0.05
                matrix.raw[tile.tile_index] = min(bonus, 0.0)
            else:
                matrix.raw[tile.tile_index] += bonus

            if bot.info_render_expansion_matrix_values:
                bot.viewInfo.bottomLeftGridText[tile] = f'x{matrix.raw[tile.tile_index]:0.3f}'

        return matrix
