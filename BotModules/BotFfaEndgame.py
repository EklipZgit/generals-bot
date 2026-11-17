from __future__ import annotations

import typing
from dataclasses import dataclass, field
from enum import Enum

import logbook
import Gather
import SearchUtils
import BotModules as BM
from base.client.map import Tile, Player
from DangerAnalyzer import ThreatType, ThreatObj
from Models.Move import Move
from Path import Path
from StrategyModels import ExpansionPotential
from Interfaces.MapMatrixInterface import MapMatrixInterface

if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot


class FfaEndgameMode(Enum):
    INACTIVE = 0
    ECONOMY = 1
    ALL_IN = 2
    TURTLE = 3
    RETALIATE = 4


@dataclass(slots=True)
class FfaEndgameDecision:
    mode: FfaEndgameMode
    target_player: int
    our_economy: int
    enemy_economy_total: int
    reason: str
    prioritizing_neutral_city: bool = False


@dataclass(slots=True)
class FfaGeneralReserve:
    required_army: int = 1
    non_target_player: int = -1
    fog_risk: int = 0
    local_threat: int = 0
    satisfied: bool = True


@dataclass(slots=True)
class FfaEndgameState:
    decision: FfaEndgameDecision
    retaliation_target: int = -1
    direct_kill_targets: typing.FrozenSet[int] = frozenset()
    reserve: FfaGeneralReserve = field(default_factory=FfaGeneralReserve)
    reserve_turn: int = -1
    reserve_gathering: bool = False


@dataclass(slots=True)
class _EndgameEnemy:
    player_index: int
    economy: int
    standing_army: int
    general_distance: float
    aggression_factor: int


@dataclass(slots=True)
class _EndgameContext:
    our_player_index: int
    our_economy: int
    enemies: typing.List[_EndgameEnemy]
    has_credited_kill: bool
    has_kill: bool | None


def _inactive_decision() -> FfaEndgameDecision:
    """Returns the default INACTIVE decision used before/without a 3-player FFA context."""
    return FfaEndgameDecision(
        mode=FfaEndgameMode.INACTIVE,
        target_player=-1,
        our_economy=0,
        enemy_economy_total=0,
        reason='not_three_player_solo_ffa',
        prioritizing_neutral_city=False)


def get_state(bot: EklipZBot) -> FfaEndgameState:
    """Returns the bot's FFA endgame state, lazily creating the inactive default."""
    state = bot.ffa_endgame
    if state is None:
        state = FfaEndgameState(decision=_inactive_decision())
        bot.ffa_endgame = state
    return state


def get_mode(bot: EklipZBot) -> FfaEndgameMode:
    """Returns the current FFA endgame mode."""
    return get_state(bot).decision.mode


def is_forced_all_in(bot: EklipZBot) -> bool:
    """True while the policy forces a losing-style all-in (ALL_IN or RETALIATE)."""
    return get_mode(bot) in (FfaEndgameMode.ALL_IN, FfaEndgameMode.RETALIATE)


def is_retaliating(bot: EklipZBot) -> bool:
    """True while the policy is retaliating against a latched aggressor."""
    return get_mode(bot) == FfaEndgameMode.RETALIATE


def is_prioritizing_neutral_city(bot: EklipZBot) -> bool:
    """True while ECONOMY mode has a reachable own-pocket neutral city to take first."""
    decision = get_state(bot).decision
    return decision.mode == FfaEndgameMode.ECONOMY and decision.prioritizing_neutral_city


def get_general_reserve(bot: EklipZBot) -> FfaGeneralReserve:
    """Returns the reserve calculated after this turn's general danger analysis."""
    return get_state(bot).reserve


def update_general_reserve(bot: EklipZBot) -> None:
    """Reserves bounded inbound defense without turning an ordinary all-in into a turtle."""
    state = get_state(bot)
    if state.decision.mode != FfaEndgameMode.ALL_IN:
        state.reserve = FfaGeneralReserve()
        state.reserve_turn = bot._map.turn
        return
    if state.reserve_turn == bot._map.turn:
        return
    # Tests/test_FFA.py::FFATests.test_should_attack_aggressor_without_overgathering_or_abandoning_general:
    # a middle-position all-in keeps the non-target's estimated inbound army covered;
    # local counterattacks from either player still matter even when seeking second.
    map_ = bot._map
    distances = SearchUtils.build_distance_map_matrix_with_skip(map_, [bot.general])
    reserve = FfaGeneralReserve()
    if state.decision.reason == 'all_in_middle':
        for enemy in map_.players:
            if enemy.dead or enemy.index in (bot.general.player, state.decision.target_player):
                continue
            reserve.non_target_player = enemy.index
            frontier = [distances[t] for t in enemy.tiles if distances[t] < 1000]
            if frontier:
                horizon = max(1, min(frontier))
                risk = bot.opponent_tracker.get_approximate_fog_army_risk(
                    enemy.index, inTurns=horizon, logContext='ffa_endgame_reserve')
                incomeBound = ((horizon + 1) // 2) * enemy.cityCount
                incomeBound += ((map_.turn % 50 + horizon) // 50) * enemy.tileCount
                reserve.fog_risk = min(risk, enemy.standingArmy + incomeBound)
                reserve.required_army = max(
                    reserve.required_army, reserve.fog_risk - horizon - horizon // 2 + 1)
    for tile in map_.get_all_tiles():
        if tile.player < 0 or map_.is_tile_on_team_with(tile, bot.general.player):
            continue
        distance = distances[tile]
        if 0 < distance <= 2:
            reserve.local_threat = max(reserve.local_threat, tile.army - distance + 1)
    threat = bot.dangerAnalyzer.fastestThreat
    if (threat is not None and threat.threatType == ThreatType.Kill
            and threat.path.tail is not None and threat.path.tail.tile == bot.general):
        reserve.local_threat = max(
            reserve.local_threat, bot.general.army + threat.threatValue + 1)
    reserve.required_army = max(reserve.required_army, reserve.local_threat)
    reserve.satisfied = bot.general.army >= reserve.required_army
    state.reserve = reserve
    state.reserve_turn = map_.turn
    if state.reserve_gathering and reserve.satisfied:
        bot.curPath = None
        bot.curPathPrio = -1
        state.reserve_gathering = False
    message = (
        f'FFA3 reserve p{reserve.non_target_player}: required={reserve.required_army} '
        f'held={bot.general.army} fogRisk={reserve.fog_risk} '
        f'localThreat={reserve.local_threat} satisfied={reserve.satisfied}')
    bot.viewInfo.add_info_line(message)
    bot.viewInfo.add_stats_line(message)
    logbook.info(message)


def reconcile_general_reserve_move(bot: EklipZBot, move: Move | None) -> Move | None:
    """Retains the ordinary all-in garrison after all other move-selection overrides."""
    if get_mode(bot) != FfaEndgameMode.ALL_IN or move is None or move.source != bot.general:
        return move
    # Tests/test_FFA.py::FFATests.test_should_attack_aggressor_without_overgathering_or_abandoning_general:
    # collinearity is not proof of blocking every counterattack; never strip this reserve.
    update_general_reserve(bot)
    required = get_general_reserve(bot).required_army
    retained = move.source.army - (
        (move.source.army - 1) // 2 if move.move_half else move.source.army - 1)
    if retained >= required:
        return move
    half = Move(move.source, move.dest, move_half=True)
    if move.source.army - half.army_moved >= required:
        bot.viewInfo.add_info_line(f'FFA3 retain reserve={required}: split {half}')
        return half
    bot.viewInfo.add_info_line(f'FFA3 retain reserve={required}: reject {move}')
    bot.curPath = None
    bot.curPathPrio = -1
    return None


def _enemy_general_distance(bot: EklipZBot, playerIndex: int) -> float:
    """Distance from our general to the enemy's best known/predicted general location."""
    genTile = None
    if playerIndex < len(bot._map.generals):
        candidate = bot._map.generals[playerIndex]
        if candidate is not None and candidate.isGeneral:
            genTile = candidate
    if genTile is None and playerIndex < len(bot.generalApproximations):
        approx = bot.generalApproximations[playerIndex]
        if approx is not None and len(approx) > 3 and approx[3] is not None:
            genTile = approx[3]
    if genTile is None:
        if playerIndex < len(bot.generalApproximations):
            approx = bot.generalApproximations[playerIndex]
            if approx is not None and len(approx) > 1:
                return bot._map.euclidDist(bot.general.x, bot.general.y, approx[0], approx[1])
        return float('inf')
    return bot._map.euclidDist(bot.general.x, bot.general.y, genTile.x, genTile.y)


def _evaluate_context(bot: EklipZBot) -> _EndgameContext | None:
    """Builds the 3-player solo-FFA economy context, or None when the policy is inactive."""
    map_ = bot._map
    if bot.general is None:
        return None
    if map_.is_2v2 or len(map_.teammates) > 0:
        return None
    selfIndex = bot.general.player
    teamIds = map_.team_ids_by_player_index
    ourTeam = teamIds[selfIndex] if selfIndex < len(teamIds) else selfIndex
    selfPlayer = map_.players[selfIndex]
    enemies: typing.List[Player] = []
    for player in map_.players:
        # dead players and self are excluded; AFK and never-seen players still count.
        if player.dead or player.index == selfIndex:
            continue
        if player.index < len(teamIds) and teamIds[player.index] == ourTeam:
            continue
        enemies.append(player)
    if len(enemies) != 2:
        return None
    if (enemies[0].index < len(teamIds) and enemies[1].index < len(teamIds)
            and teamIds[enemies[0].index] == teamIds[enemies[1].index]):
        return None
    ourEconomy = selfPlayer.tileCount + 25 * selfPlayer.cityCount
    enemyEconomies = []
    for enemy in enemies:
        enemyEconomies.append(
            _EndgameEnemy(
                player_index=enemy.index,
                economy=enemy.tileCount + 25 * enemy.cityCount,
                standing_army=enemy.standingArmy,
                general_distance=_enemy_general_distance(bot, enemy.index),
                aggression_factor=enemy.aggression_factor))
    # Credited-kill is three-valued: the server's authoritative has_kill wins whenever it is
    # known. Only an unknown (None) value falls back to the legacy capturedBy/serialized
    # direct-target evidence used by older maps and payloads; an explicit False is
    # authoritative and must not be overridden by a stale direct-kill record.
    selfHasKill = selfPlayer.has_kill
    legacyDirectKill = False
    if selfHasKill is None:
        legacyDirectKill = any(p.dead and p.capturedBy == selfIndex for p in map_.players)
        if not legacyDirectKill:
            # capturedBy is runtime-only and is not preserved across txtmap import; a direct kill
            # recorded into endgame state at save time still counts while that player stays dead.
            state = get_state(bot)
            if state.direct_kill_targets:
                legacyDirectKill = any(
                    p.dead and p.index in state.direct_kill_targets for p in map_.players)
    hasCreditedKill = selfHasKill if selfHasKill is not None else legacyDirectKill
    return _EndgameContext(
        our_player_index=selfIndex,
        our_economy=ourEconomy,
        enemies=enemyEconomies,
        has_credited_kill=hasCreditedKill,
        has_kill=selfHasKill)


def _weaker_enemy_key(enemy: _EndgameEnemy) -> typing.Tuple[int, int, float, int]:
    """Orders enemies weakest-first by economy, army, general distance, then index."""
    return (enemy.economy, enemy.standing_army, enemy.general_distance, enemy.player_index)


def _pick_weaker_enemy(enemies: typing.List[_EndgameEnemy]) -> _EndgameEnemy:
    """Picks the weaker enemy by economy, then army, distance, and index."""
    return min(enemies, key=_weaker_enemy_key)


def _is_serious_aggressor(bot: EklipZBot, playerIndex: int) -> bool:
    """True when the enemy is a serious aggressor (aggression factor over 120)."""
    return BM.BotTimings.BotTimings.is_player_aggressive(bot, playerIndex)


def _pick_rule2_target(bot: EklipZBot, ctx: _EndgameContext) -> int:
    """Target for the middle position (beat each enemy but not their combined economy)."""
    lockTarget = bot.ffa_exclusive_target_lock
    for enemy in ctx.enemies:
        if enemy.player_index == lockTarget:
            return lockTarget
    aggressors = [e for e in ctx.enemies if _is_serious_aggressor(bot, e.player_index)]
    if len(aggressors) > 0:
        return max(
            aggressors,
            key=lambda e: (e.aggression_factor, -e.economy, -e.general_distance, -e.player_index)).player_index
    return min(
        ctx.enemies,
        key=lambda e: (e.general_distance, e.economy, e.standing_army, e.player_index)).player_index


def _target_rationale(bot: EklipZBot, ctx: _EndgameContext, reason: str, target: int) -> str:
    """Short explanation of why `target` was chosen for the forced mode (ViewInfo diagnostics)."""
    if target == -1:
        return 'none'
    if reason.startswith('retaliation'):
        return f'retaliation_p{target}'
    if reason == 'economy_dominant':
        return 'passive_economy'
    if reason == 'turtle_after_credited_kill':
        return 'turtle_after_kill'
    if bot.ffa_exclusive_target_lock == target:
        return 'locked_target'
    enemy = next((e for e in ctx.enemies if e.player_index == target), None)
    if enemy is None:
        return 'unknown'
    if reason == 'all_in_middle':
        if _is_serious_aggressor(bot, target):
            return 'middle_rule2_aggressor'
        return 'middle_rule2_closest'
    weakest = _pick_weaker_enemy(ctx.enemies)
    if weakest.player_index == target:
        return 'weakest'
    return 'selected'


def _decide_mode_and_target(
        bot: EklipZBot,
        ctx: _EndgameContext) -> typing.Tuple[FfaEndgameMode, int, str]:
    """Applies the economy rules and returns (mode, target, reason)."""
    ourEconomy = ctx.our_economy
    enemyTotal = ctx.enemies[0].economy + ctx.enemies[1].economy
    e0 = ctx.enemies[0]
    e1 = ctx.enemies[1]
    if ourEconomy > enemyTotal:
        return FfaEndgameMode.ECONOMY, -1, 'economy_dominant'
    if ourEconomy > e0.economy and ourEconomy > e1.economy:
        return FfaEndgameMode.ALL_IN, _pick_rule2_target(bot, ctx), 'all_in_middle'
    if ourEconomy > e0.economy or ourEconomy > e1.economy:
        weaker = _pick_weaker_enemy(ctx.enemies)
        return FfaEndgameMode.ALL_IN, weaker.player_index, 'all_in_weaker'
    if ctx.has_credited_kill:
        return FfaEndgameMode.TURTLE, -1, 'turtle_after_credited_kill'
    weaker = _pick_weaker_enemy(ctx.enemies)
    return FfaEndgameMode.ALL_IN, weaker.player_index, 'all_in_weakest'


def _neutral_city_priority_active(bot: EklipZBot) -> bool:
    """True when a reachable own-pocket neutral city exists for ECONOMY priority."""
    if bot.shortest_path_to_target_player is None or bot.cityAnalyzer is None:
        return False
    return BM.BotCityOps.BotCityOps.find_neutral_city_path(bot) is not None


def _clear_attack_routes(bot: EklipZBot, reason: str) -> None:
    """Clears committed attack routes (curPath, quick-kill, stealth, hunt) for a retarget."""
    bot.curPath = None
    bot.curPathPrio = -1
    bot.committed_quick_kill = None
    bot.committed_quick_kill_cutoff = 0
    if bot.stealth_all_in is not None:
        if bot.stealth_all_in.committed_route is not None:
            BM.BotStealthAllIn.BotStealthAllIn._abort_committed_route(bot, reason)
        else:
            BM.BotStealthAllIn.BotStealthAllIn.clear_uncommitted_state(bot)
    BM.BotStealthAllIn.BotStealthAllIn.clear_pending_hunt_job(bot)
    bot.stealth_all_in_cannot_kill_counter = 0


def _clear_target_plans(bot: EklipZBot) -> None:
    """Clears target-specific plans on forced-mode entry or policy retarget."""
    turn = bot._map.turn
    bot.expansion_plan = ExpansionPotential(0, 0, 0, None, [], 0.0, turn)
    bot.city_expand_plan = None
    bot.enemy_expansion_plan = None
    _clear_attack_routes(bot, 'ffa_endgame_retarget')


def _apply_mode_side_effects(
        bot: EklipZBot,
        oldMode: FfaEndgameMode,
        oldTarget: int,
        newMode: FfaEndgameMode,
        newTarget: int,
        prioritizingNeutralCity: bool) -> None:
    """Syncs bot all-in flags and clears stale plans on forced-mode entry/retarget."""
    forcedNow = newMode in (FfaEndgameMode.ALL_IN, FfaEndgameMode.RETALIATE)
    forcedBefore = oldMode in (FfaEndgameMode.ALL_IN, FfaEndgameMode.RETALIATE)
    if forcedNow:
        bot.is_all_in_losing = True
        bot.is_all_in_army_advantage = False
        bot.all_in_city_behind = False
        bot.is_winning_gather_cyclic = False
        bot.force_far_gathers = False
    elif newMode == FfaEndgameMode.TURTLE:
        bot.is_all_in_losing = False
        bot.is_all_in_army_advantage = False
        bot.all_in_city_behind = False
        bot.is_winning_gather_cyclic = False
    elif newMode == FfaEndgameMode.ECONOMY:
        bot.is_all_in_losing = False
        if prioritizingNeutralCity:
            bot.is_all_in_army_advantage = False
            bot.all_in_city_behind = False
            bot.is_winning_gather_cyclic = False
    elif newMode == FfaEndgameMode.INACTIVE and forcedBefore:
        bot.is_all_in_losing = False
        bot.is_all_in_army_advantage = False
        bot.all_in_city_behind = False
        bot.is_winning_gather_cyclic = False
        bot.all_in_army_advantage_counter = 0
        bot.all_in_losing_counter = 0
    enteredForced = forcedNow and not forcedBefore
    retargeted = forcedNow and forcedBefore and newTarget != oldTarget
    enteredTurtle = newMode == FfaEndgameMode.TURTLE and oldMode != FfaEndgameMode.TURTLE
    enteredEconomyCity = (newMode == FfaEndgameMode.ECONOMY and oldMode != FfaEndgameMode.ECONOMY
                          and prioritizingNeutralCity)
    if enteredForced or retargeted:
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # all_in_army_advantage_counter is the countdown consumed by get_all_in_hit_general_turns;
        # resetting it on every stable update froze the gather ETA at "in 30t" forever. Reset only
        # on forced entry/retarget so a stable forced all-in keeps counting down and launches.
        bot.all_in_army_advantage_counter = 0
        bot.all_in_losing_counter = 0
        _clear_target_plans(bot)
    elif enteredTurtle:
        # entering TURTLE abandons every stale attack plan/committed route; a stable TURTLE keeps
        # its own owned-only gather curPath untouched.
        _clear_target_plans(bot)
    elif enteredEconomyCity:
        # ECONOMY city priority must not let a committed attack route return before the city branch.
        _clear_attack_routes(bot, 'ffa_endgame_city_priority')


def update_policy(bot: EklipZBot, evaluateCityPriority: bool = True) -> None:
    """Recomputes the 3-player FFA endgame decision and applies its side effects.

    evaluateCityPriority gates the expensive reachable-neutral-city path search; early scan-time
    refreshes pass False so unattackable/target queries see the mode without paying for city paths,
    and the authoritative pre-pick refresh passes True once paths are current.
    """
    state = get_state(bot)
    oldDecision = state.decision
    ctx = _evaluate_context(bot)
    latchedRetaliation = -1
    if ctx is not None and state.retaliation_target != -1:
        for enemy in ctx.enemies:
            if enemy.player_index == state.retaliation_target:
                latchedRetaliation = state.retaliation_target
                break
    if latchedRetaliation != -1:
        mode = FfaEndgameMode.RETALIATE
        target = latchedRetaliation
        reason = 'retaliation_latched'
        newRetaliation = latchedRetaliation
    elif ctx is None:
        mode = FfaEndgameMode.INACTIVE
        target = -1
        reason = 'not_three_player_solo_ffa'
        newRetaliation = -1
    else:
        mode, target, reason = _decide_mode_and_target(bot, ctx)
        newRetaliation = -1
        if mode == FfaEndgameMode.TURTLE:
            aggressors = [e for e in ctx.enemies if _is_serious_aggressor(bot, e.player_index)]
            if len(aggressors) > 0:
                worst = max(
                    aggressors,
                    key=lambda e: (e.aggression_factor, -e.economy, -e.general_distance, -e.player_index))
                mode = FfaEndgameMode.RETALIATE
                target = worst.player_index
                reason = 'retaliation_aggressor'
                newRetaliation = worst.player_index
    enemyTotal = 0
    ourEconomy = 0
    if ctx is not None:
        enemyTotal = ctx.enemies[0].economy + ctx.enemies[1].economy
        ourEconomy = ctx.our_economy
    prioritizingCity = (evaluateCityPriority and mode == FfaEndgameMode.ECONOMY
                        and _neutral_city_priority_active(bot))
    newDecision = FfaEndgameDecision(
        mode=mode,
        target_player=target,
        our_economy=ourEconomy,
        enemy_economy_total=enemyTotal,
        reason=reason,
        prioritizing_neutral_city=prioritizingCity)
    _apply_mode_side_effects(
        bot, oldDecision.mode, oldDecision.target_player, mode, target, prioritizingCity)
    state.retaliation_target = newRetaliation
    state.decision = newDecision
    if evaluateCityPriority and mode != FfaEndgameMode.INACTIVE:
        # User request: document the FFA endgame decision process every authoritative turn.
        # Info lines break down our economy vs each opponent, credited-kill state, serious
        # aggressors, and the branch reason; the stats line is the final selected state.
        enemyParts = []
        for enemy in ctx.enemies:
            enemyParts.append(
                f'p{enemy.player_index}={enemy.economy}t{enemy.standing_army}a aggro{enemy.aggression_factor}')
        ourPlayer = bot._map.players[ctx.our_player_index]
        hasKillText = 'legacy' if ourPlayer.has_kill is None else str(ourPlayer.has_kill)
        aggressorIdx = [e.player_index for e in ctx.enemies if _is_serious_aggressor(bot, e.player_index)]
        aggressorText = ','.join(f'p{i}' for i in aggressorIdx) if aggressorIdx else 'none'
        rationale = _target_rationale(bot, ctx, reason, target)
        bot.viewInfo.add_info_line(
            f'FFA3 decide: {mode.name} target=p{target} ourEcon={ourEconomy} enemies={enemyTotal} '
            f'[{"; ".join(enemyParts)}] hasKill={hasKillText} aggressors={aggressorText} '
            f'reason={reason} pick={rationale}')
        targetName = ''
        if 0 <= target < len(bot._map.usernames):
            targetName = f' {bot._map.usernames[target]}'
        enemyEconBreakdown = '+'.join(str(e.economy) for e in ctx.enemies)
        bot.viewInfo.add_stats_line(
            f'FFA3 {mode.name} -> p{target}{targetName} | econ {ourEconomy} vs {enemyEconBreakdown} | {reason}')
        logbook.info(
            f'FfaEndgame update_policy: mode={mode.name} target={target} '
            f'ourEcon={ourEconomy} enemyEcon={enemyTotal} reason={reason} '
            f'retaliation={newRetaliation} cityPriority={prioritizingCity} hasKill={hasKillText}')


def update_retaliation(bot: EklipZBot) -> None:
    """Escalates TURTLE to RETALIATE on a concrete kill threat against our general."""
    state = get_state(bot)
    if state.decision.mode != FfaEndgameMode.TURTLE:
        return
    threat = bot.dangerAnalyzer.fastestThreat
    if threat is None or threat.threatType != ThreatType.Kill:
        return
    tailTile = threat.path.tail.tile
    if tailTile is None or not tailTile.isGeneral or tailTile.player != bot.general.player:
        return
    aggressor = threat.threatPlayer
    if aggressor < 0 or aggressor >= len(bot._map.players):
        return
    aggressorPlayer = bot._map.players[aggressor]
    if (aggressorPlayer.dead or aggressorPlayer.index == bot.general.player
            or aggressor in bot._map.teammates):
        return
    state.retaliation_target = aggressor
    update_policy(bot)
    # synchronize the forced target into live targeting state so the same-turn revenge move aims
    # at the offender instead of the stale turtle target (-1). The target reset clears the forced
    # flags, so update_policy is re-run afterwards to re-assert them.
    newTarget = state.decision.target_player
    if newTarget != -1 and newTarget != bot.targetPlayer:
        oldTarget = bot.targetPlayer
        bot.targetPlayer = newTarget
        if bot.opponent_tracker is not None:
            bot.opponent_tracker.targetPlayer = newTarget
        bot.targetPlayerObj = bot._map.players[newTarget]
        bot._reset_all_in_state_after_target_player_change(oldTarget, newTarget)
        bot.recalculate_player_paths(force=True)
        update_policy(bot)
    logbook.info(f'FfaEndgame retaliation escalated vs p{aggressor} from kill threat')


def _gather_forward_to_target(bot: EklipZBot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
    """Gathers army forward toward the forced target when attack helpers produce nothing."""
    targets: typing.List[Tile] = []
    if bot.target_player_gather_targets is not None:
        targets.extend(bot.target_player_gather_targets)
    if bot.targetPlayerExpectedGeneralLocation is not None:
        targets.append(bot.targetPlayerExpectedGeneralLocation)
    if len(targets) == 0:
        return None
    hitGeneralInTurns = BM.BotCombatOps.BotCombatOps.get_all_in_hit_general_turns(bot)
    attackSkips = BM.BotCombatOps.BotCombatOps._get_all_in_attack_route_skips(bot, targets)
    gathCapPlan = Gather.gather_approximate_turns_to_tiles(
        bot._map,
        rootTiles=targets,
        approximateTargetTurns=hitGeneralInTurns,
        asPlayer=bot.general.player,
        gatherMatrix=BM.BotGatherOps.BotGatherOps.get_gather_tiebreak_matrix(bot),
        negativeTiles=defenseCriticalTileSet,
        skipTiles=attackSkips,
        prioritizeCaptureHighArmyTiles=False,
        useTrueValueGathered=True,
        includeGatherPriorityAsEconValues=True,
        includeCapturePriorityAsEconValues=False,
        timeLimit=min(0.05, BM.BotTimings.BotTimings.get_remaining_move_time(bot)))
    if gathCapPlan is None:
        return None
    move = gathCapPlan.get_first_move()
    if move is None:
        return None
    bot.curPath = gathCapPlan
    bot.gatherNodes = gathCapPlan.root_nodes
    return move


def get_retaliate_move(
        bot: EklipZBot,
        threat: ThreatObj | None,
        kingKillPath: Path | None,
        raceChance: float,
        defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
    """Executes the retaliation attack, ignoring all defense branches."""
    # UnitTests/test_FfaEndgame.py::test_attack_move_continues_policy_curpath_before_fresh_stealth_and_generic
    # and ::test_attack_move_ready_forward_advance_beats_rear_gather: forced attack priority is
    # committed route -> existing policy curPath -> ready forward advance -> only then fresh
    # uncommitted stealth/generic gather, so gather-in-place cannot displace real forward progress.
    move = BM.BotStealthAllIn.BotStealthAllIn.get_committed_route_move(bot, None, set(), None, 0.0)
    if move is not None:
        return move
    foundMove, curPathMove = BM.BotPathingUtils.BotPathingUtils.continue_cur_path(bot, None, set())
    if foundMove and curPathMove is not None:
        return curPathMove
    move = _get_forward_fallback_move(bot, set())
    if move is not None:
        return move
    move = BM.BotStealthAllIn.BotStealthAllIn.get_stealth_all_in_move(bot, set())
    if move is not None:
        return move
    move = BM.BotCombatOps.BotCombatOps.get_all_in_move(bot, set())
    if move is not None:
        return move
    move = _gather_forward_to_target(bot, set())
    if move is not None:
        return move
    return None


def get_attack_move(
        bot: EklipZBot,
        threat: ThreatObj | None,
        defenseCriticalTileSet: typing.Set[Tile],
        kingKillPath: Path | None,
        raceChance: float) -> Move | None:
    """Routes committed/stealth/generic attack for forced ALL_IN after lethal defense."""
    # UnitTests/test_FfaEndgame.py::test_attack_move_continues_policy_curpath_before_fresh_stealth_and_generic
    # and ::test_attack_move_ready_forward_advance_beats_rear_gather: forced attack priority is
    # committed route -> existing policy curPath -> ready forward advance -> only then fresh
    # uncommitted stealth/generic gather, so gather-in-place cannot displace real forward progress.
    move = BM.BotStealthAllIn.BotStealthAllIn.get_committed_route_move(
        bot, threat, defenseCriticalTileSet, kingKillPath, raceChance)
    if move is not None:
        return move
    foundMove, curPathMove = BM.BotPathingUtils.BotPathingUtils.continue_cur_path(
        bot, threat, defenseCriticalTileSet)
    if foundMove and curPathMove is not None:
        return curPathMove
    move = _get_forward_fallback_move(bot, defenseCriticalTileSet)
    if move is not None:
        return move
    move = BM.BotStealthAllIn.BotStealthAllIn.get_stealth_all_in_move(bot, defenseCriticalTileSet)
    if move is not None:
        return move
    move = BM.BotCombatOps.BotCombatOps.get_all_in_move(bot, defenseCriticalTileSet)
    if move is not None:
        return move
    move = _gather_forward_to_target(bot, defenseCriticalTileSet)
    if move is not None:
        return move
    return None



def _collect_target_frontier_roots(bot: EklipZBot) -> typing.List[Tile]:
    """Collects passable target-owned and valid target-general-candidate root tiles."""
    map_ = bot._map
    ourPlayer = bot.general.player
    target = get_state(bot).decision.target_player
    if target == -1:
        target = bot.targetPlayer
    roots: typing.List[Tile] = []
    seen: typing.Set[int] = set()

    def _add(tile: Tile | None) -> None:
        """Adds a passable non-foreign root candidate once."""
        if tile is None or tile.tile_index in seen:
            return
        if not tile.isPathable or tile.isObstacle:
            return
        # never root on another player's tile; only the target's own or undiscovered candidates.
        if tile.player >= 0 and tile.player != target and not map_.is_tile_on_team_with(tile, ourPlayer):
            return
        if tile.player == ourPlayer:
            return
        seen.add(tile.tile_index)
        roots.append(tile)

    if target != -1:
        for tile in map_.get_all_tiles():
            if tile.player == target:
                _add(tile)
        for tile in (bot.alt_en_gen_positions[target] if target < len(bot.alt_en_gen_positions) else []):
            _add(tile)
        _add(bot.targetPlayerExpectedGeneralLocation)
    return roots


def _collect_target_general_roots(bot: EklipZBot, include_alternates: bool) -> typing.List[Tile]:
    """Collects the target's best general-hunt root tiles before generic target land.

    A discovered general wins outright; otherwise the current predicted location is the
    exclusive first objective. Alternate candidates are used only when no authoritative
    predicted root exists or when include_alternates asks for the fallback set.
    """
    map_ = bot._map
    ourPlayer = bot.general.player
    target = get_state(bot).decision.target_player
    if target == -1:
        target = bot.targetPlayer
    roots: typing.List[Tile] = []
    seen: typing.Set[int] = set()

    def _add(tile: Tile | None) -> None:
        """Adds a passable target/undiscovered general candidate once."""
        if tile is None or tile.tile_index in seen:
            return
        if not tile.isPathable or tile.isObstacle:
            return
        if tile.player >= 0 and tile.player != target and not map_.is_tile_on_team_with(tile, ourPlayer):
            return
        if tile.player == ourPlayer:
            return
        seen.add(tile.tile_index)
        roots.append(tile)

    if target == -1:
        return roots
    if target < len(map_.generals):
        general = map_.generals[target]
        if general is not None and general.isGeneral and general.player == target:
            _add(general)
            return roots
    _add(bot.targetPlayerExpectedGeneralLocation)
    if not include_alternates:
        return roots
    # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
    # and ::test_should_attack_predicted_general_during_ffa_all_in: an authoritative
    # predicted root can be temporarily sealed off by fog/other-player territory. The
    # fallback pass must still include alternate general candidates instead of falling
    # straight through to arbitrary target land just because a prediction exists.
    if target < len(bot.alt_en_gen_positions):
        for tile in bot.alt_en_gen_positions[target]:
            _add(tile)
    return roots


def _owned_frontier_nearest_target(bot: EklipZBot, targetRefs: typing.List[Tile]) -> typing.List[Tile]:
    """Returns our owned border tiles closest to the target region as owned roots."""
    map_ = bot._map
    ourPlayer = bot.general.player
    owned = [t for t in map_.get_all_tiles() if t.player == ourPlayer and t.isPathable and not t.isObstacle]
    if not owned:
        return []
    if not targetRefs:
        return owned
    frontier: typing.List[Tile] = []
    for tile in owned:
        for n in tile.movable:
            if n.player != ourPlayer and n.isPathable and not n.isObstacle:
                frontier.append(tile)
                break
    if not frontier:
        frontier = owned

    def _distToTarget(tile: Tile) -> float:
        """Euclidean distance from a tile to the nearest target-region reference."""
        best = float('inf')
        for ref in targetRefs:
            d = map_.euclidDist(tile.x, tile.y, ref.x, ref.y)
            if d < best:
                best = d
        return best

    minDist = min(_distToTarget(t) for t in frontier)
    margin = 6
    return [t for t in frontier if _distToTarget(t) <= minDist + margin]


def _step_toward_distmap(
        bot: EklipZBot,
        distMap: typing.Any,
        blocked: typing.Set[Tile],
        allowGeneral: bool) -> Move | None:
    """Picks a substantial owned stack and returns its first legal step toward lower distance."""
    map_ = bot._map
    ourPlayer = bot.general.player
    candidates: typing.List[Tile] = []
    for tile in map_.get_all_tiles():
        if tile.player != ourPlayer or tile.army < 2 or not tile.isPathable or tile.isObstacle:
            continue
        if tile in blocked:
            continue
        if not allowGeneral and tile.isGeneral:
            continue
        if distMap[tile] >= 1000:
            continue
        if len(tile.movable) == 0:
            continue
        candidates.append(tile)
    if not candidates and not allowGeneral:
        return _step_toward_distmap(bot, distMap, blocked, True)
    if not candidates:
        return None
    minDist = min(distMap[t] for t in candidates)
    nearFront = [t for t in candidates if distMap[t] <= minDist + 4]
    stack = max(nearFront, key=lambda t: (t.army, -distMap[t], -t.tile_index))
    bestNext: Tile | None = None
    bestDist = distMap[stack]
    for n in stack.movable:
        if n in blocked or not n.isPathable or n.isObstacle:
            continue
        nd = distMap[n]
        if nd >= bestDist or nd >= 1000:
            continue
        if n.player != ourPlayer and stack.army - 1 <= n.army:
            continue
        if bestNext is None or nd < distMap[bestNext] or (nd == distMap[bestNext] and n.army > bestNext.army):
            bestNext = n
            bestDist = nd
    if bestNext is None:
        return None
    return Move(stack, bestNext)


def _build_forward_route(
        bot: EklipZBot,
        start: Tile,
        distMap: typing.Any,
        skip: typing.Set[Tile],
        target: int,
        allowGeneralTile: bool) -> typing.Tuple[typing.List[Tile], int]:
    """Greedy downhill route from `start` toward the target frontier, projecting carried army.

    Each departure leaves 1 behind; own arrivals merge resident army while enemy/neutral
    arrivals subtract their defense. The route stops at the first target-owned frontier tile
    (distMap 0), when no survivable downhill step remains, or when projected army drops below 2.
    """
    ourPlayer = bot.general.player
    route: typing.List[Tile] = [start]
    cur = start
    curArmy = start.army
    visited: typing.Set[int] = {start.tile_index}
    for _ in range(80):
        bestNext: Tile | None = None
        bestKey: typing.Tuple[int, int, int] | None = None
        for n in cur.movable:
            if n in skip or not n.isPathable or n.isObstacle or n.tile_index in visited:
                continue
            # Tests/test_FFA.py::FFATests.test_should_attack_aggressor_without_overgathering_or_abandoning_general:
            # when the protected general cannot spare its reserve, a non-general spear must
            # not merge onto it; the following step would become a general-source move, be
            # rejected by reconcile_general_reserve_move, and wipe the committed route.
            if n == bot.general and not allowGeneralTile:
                continue
            nd = distMap[n]
            if nd >= 1000 or nd >= distMap[cur]:
                continue
            moved = curArmy - 1
            if n.player == ourPlayer:
                pass
            elif n.player == target or n.player < 0:
                # enemy/neutral arrival must carry enough army to survive the defense.
                if moved <= n.army:
                    continue
            else:
                continue
            own = 0 if n.player == ourPlayer else 1
            # own tiles: prefer higher resident army (more pickup); enemy/neutral: lower defense.
            armyKey = -n.army if n.player == ourPlayer else n.army
            key = (nd, own, armyKey)
            if bestKey is None or key < bestKey:
                bestKey = key
                bestNext = n
        if bestNext is None:
            break
        moved = curArmy - 1
        if bestNext.player == ourPlayer:
            curArmy = moved + bestNext.army
        else:
            curArmy = moved - bestNext.army
        if curArmy < 2:
            break
        route.append(bestNext)
        cur = bestNext
        visited.add(bestNext.tile_index)
        if distMap[bestNext] == 0:
            break
    return route, curArmy


def _commit_forward_path(
        bot: EklipZBot,
        distMap: typing.Any,
        skip: typing.Set[Tile],
        target: int) -> Move | None:
    """Builds and commits the best survivable forward Path toward the target frontier.

    Considers the top own stacks by army including the general, keeps only routes that reach a
    target-owned frontier tile alive, and commits the winner to bot.curPath so the next turn's
    continue_cur_path executes the same spear instead of recomputing a fresh gather.
    """
    map_ = bot._map
    ourPlayer = bot.general.player
    candidates: typing.List[Tile] = []
    for tile in map_.get_all_tiles():
        if tile.player != ourPlayer or tile.army < 2 or not tile.isPathable or tile.isObstacle:
            continue
        if tile in skip or distMap[tile] >= 1000 or len(tile.movable) == 0:
            continue
        candidates.append(tile)
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t.army, distMap[t], t.tile_index))
    general = bot.general
    # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left and
    # Tests/test_FFA.py::FFATests.test_should_attack_aggressor_without_overgathering_or_abandoning_general:
    # the forced attack must field the strongest spear it can actually launch, not starve itself
    # waiting for a non-general stack that cannot reach the target in time. The general is a valid
    # source only while it can still retain the computed reserve after leaving.
    reserve = get_general_reserve(bot)
    generalCanSpare = (general is not None and general.army >= reserve.required_army
                       and general.army >= 2 and general.isPathable and not general.isObstacle
                       and general not in skip and distMap[general] < 1000
                       and len(general.movable) > 0)
    sources = [t for t in candidates if not t.isGeneral][:4]
    if generalCanSpare and general not in sources:
        sources.append(general)
    bestRoute: typing.List[Tile] | None = None
    bestArmy = -1
    for start in sources:
        route, finalArmy = _build_forward_route(bot, start, distMap, skip, target, generalCanSpare)
        if len(route) < 2 or distMap[route[-1]] != 0:
            continue
        routeLen = len(route)
        if (finalArmy > bestArmy
                or (finalArmy == bestArmy and bestRoute is not None and routeLen < len(bestRoute))
                or (finalArmy == bestArmy and bestRoute is not None and routeLen == len(bestRoute)
                    and route[0].tile_index < bestRoute[0].tile_index)):
            bestRoute = route
            bestArmy = finalArmy
    if bestRoute is None:
        return None
    path = Path()
    path.add_start(bestRoute[0])
    for t in bestRoute[1:]:
        path.add_next(t)
    bot.curPath = path
    move = path.get_first_move()
    logbook.info(
        f'FFA_ENDGAME_ADVANCE turn={map_.turn} source={bestRoute[0]} frontier={bestRoute[-1]} '
        f'pathLen={len(bestRoute)} projectedArmy={bestArmy}')
    return move


def _get_forward_fallback_move(bot: EklipZBot, defenseCriticalTiles: typing.Set[Tile]) -> Move | None:
    """Deterministic fog-safe forward move toward the forced target when gathers produce nothing.

    Commits the best survivable forward Path toward the closest reachable target frontier using a
    distance map over passable tiles; falls back to a single forward step and then our owned
    frontier nearest the target region. Never uses the true map or a hidden enemy general.
    """
    map_ = bot._map
    ourPlayer = bot.general.player
    decision = get_state(bot).decision
    target = decision.target_player if decision.target_player != -1 else bot.targetPlayer
    # Tests/test_FFA.py::FFATests.test_should_attack_predicted_general_during_ffa_all_in:
    # when the fog model has a general prediction, the all-in must route at that tile
    # before it is allowed to nibble the closest arbitrary target-owned frontier. The
    # candidate/territory sets remain fallbacks for no-prediction or unreachable fog cases.
    predictedRoots = _collect_target_general_roots(bot, include_alternates=False)
    candidateRoots = _collect_target_general_roots(bot, include_alternates=True)
    frontierRoots = _collect_target_frontier_roots(bot)
    guidanceRoots = predictedRoots or candidateRoots or frontierRoots
    otherEnemy = {
        t for t in map_.get_all_tiles()
        if t.player >= 0 and t.player != ourPlayer and not map_.is_tile_on_team_with(t, ourPlayer)
        and t.player != target}
    skip = set(otherEnemy) | set(defenseCriticalTiles)
    for t in map_.get_all_tiles():
        # never path through or capture a city wall the bot has not confirmed, and never let a
        # forced attack detour onto a neutral city (bystander capture is forbidden in FFA modes).
        if t.isCity and (not t.discovered or t.player < 0):
            skip.add(t)
    for targetRefs, huntLabel in (
            (predictedRoots, 'predicted_general'),
            (candidateRoots, 'general_candidates'),
            (frontierRoots, 'target_frontier')):
        if not targetRefs:
            continue
        distMap = SearchUtils.build_distance_map_matrix_with_skip(
            map_, targetRefs, skipTiles=skip, maxDepth=120)
        move = _commit_forward_path(bot, distMap, skip, target)
        if move is not None:
            if huntLabel != 'target_frontier':
                rootsText = ','.join(str(t) for t in targetRefs[:4])
                bot.viewInfo.add_info_line(
                    f'FFA3 hunt {huntLabel} p{target} @{rootsText}: {move}')
            return move
        move = _step_toward_distmap(bot, distMap, skip, False)
        if move is not None:
            if huntLabel != 'target_frontier':
                rootsText = ','.join(str(t) for t in targetRefs[:4])
                bot.viewInfo.add_info_line(
                    f'FFA3 hunt {huntLabel} p{target} @{rootsText}: {move}')
            return move
    ownedRoots = _owned_frontier_nearest_target(bot, guidanceRoots)
    if not ownedRoots:
        return None
    ownedDist = SearchUtils.build_distance_map_matrix_with_skip(
        map_, ownedRoots, skipTiles=skip, maxDepth=120)
    return _step_toward_distmap(bot, ownedDist, skip, False)


def _turtle_move(bot: EklipZBot) -> Move | None:
    """Top-priority owned-only gather to our general; None is a deliberate pass."""
    map_ = bot._map
    player = bot.general.player
    skipTiles = {t for t in map_.get_all_tiles() if not map_.is_tile_on_team_with(t, player)}
    gathCapPlan = Gather.gather_approximate_turns_to_tiles(
        map_,
        rootTiles=[bot.general],
        approximateTargetTurns=50,
        asPlayer=player,
        gatherMatrix=BM.BotGatherOps.BotGatherOps.get_gather_tiebreak_matrix(bot),
        captureMatrix=None,
        negativeTiles=None,
        skipTiles=skipTiles,
        prioritizeCaptureHighArmyTiles=False,
        useTrueValueGathered=True,
        includeGatherPriorityAsEconValues=True,
        includeCapturePriorityAsEconValues=False,
        timeLimit=min(0.05, BM.BotTimings.BotTimings.get_remaining_move_time(bot)))
    if gathCapPlan is None:
        return None
    move = gathCapPlan.get_first_move()
    if move is None:
        return None
    bot.curPath = gathCapPlan
    bot.gatherNodes = gathCapPlan.root_nodes
    return move


def _economy_city_move(bot: EklipZBot) -> Move | None:
    """Captures or gathers toward the prioritized neutral city; None falls through.

    Only a neutral city is eligible: capture_cities can return an enemy-city contest, so its
    result is accepted only when it actually targets a neutral city tile.
    """
    path, move, _planOption = BM.BotCityOps.BotCityOps.capture_cities_with_plan_option(
        bot, set(), forceNeutralCapture=True, includeContestOption=False,
        preferNeutralCapture=True, ignoreContestSuppressionForNeutral=True)
    captureTarget: Tile | None = None
    if move is not None:
        captureTarget = move.dest
    elif path is not None and path.tail is not None:
        captureTarget = path.tail.tile
    if captureTarget is not None and captureTarget.isCity and captureTarget.player == -1:
        if move is not None:
            return move
        firstMove = BM.BotPathingUtils.BotPathingUtils.get_first_path_move(bot, path)
        if firstMove is not None:
            return firstMove
    neutPath = BM.BotCityOps.BotCityOps.find_neutral_city_path(bot)
    if neutPath is None or neutPath.tail is None or neutPath.tail.tile is None:
        return None
    cityTile = neutPath.tail.tile
    if cityTile.player != -1:
        return None
    map_ = bot._map
    player = bot.general.player
    enemyTiles = {
        t for t in map_.get_all_tiles()
        if t.player >= 0 and not map_.is_tile_on_team_with(t, player)}
    gathCapPlan = Gather.gather_approximate_turns_to_tiles(
        map_,
        rootTiles=[cityTile],
        approximateTargetTurns=max(2, neutPath.length),
        asPlayer=player,
        gatherMatrix=BM.BotGatherOps.BotGatherOps.get_gather_tiebreak_matrix(bot),
        captureMatrix=None,
        negativeTiles=None,
        skipTiles=enemyTiles,
        prioritizeCaptureHighArmyTiles=False,
        useTrueValueGathered=True,
        includeGatherPriorityAsEconValues=True,
        includeCapturePriorityAsEconValues=False,
        timeLimit=min(0.05, BM.BotTimings.BotTimings.get_remaining_move_time(bot)))
    if gathCapPlan is None:
        return None
    move = gathCapPlan.get_first_move()
    if move is None:
        return None
    bot.curPath = gathCapPlan
    bot.gatherNodes = gathCapPlan.root_nodes
    return move


def get_move(bot: EklipZBot) -> Move | None:
    """Returns the TURTLE owned-only gather or ECONOMY neutral-city move, else None."""
    decision = get_state(bot).decision
    if decision.mode == FfaEndgameMode.TURTLE:
        return _turtle_move(bot)
    if decision.mode == FfaEndgameMode.ECONOMY and decision.prioritizing_neutral_city:
        return _economy_city_move(bot)
    return None


def save_state(bot: EklipZBot) -> typing.Dict[str, str]:
    """Serializes the latched retaliation target and direct-kill history for txtmap resume.

    Direct-kill targets are recomputed from live capturedBy and merged with any previously
    restored history so a kill survives repeated save/load cycles.
    """
    state = get_state(bot)
    killedTargets = set(state.direct_kill_targets)
    playerIndex = bot._map.player_index
    for player in bot._map.players:
        if player.dead and player.capturedBy == playerIndex:
            killedTargets.add(player.index)
    return {
        'bot_ffa_endgame_retaliation_target': str(state.retaliation_target),
        'bot_ffa_endgame_direct_kill_targets': ','.join(str(i) for i in sorted(killedTargets)),
    }


def load_state(bot: EklipZBot, resume_data: typing.Dict[str, str]) -> None:
    """Restores the latched retaliation target and direct-kill history from resume data."""
    state = get_state(bot)
    state.retaliation_target = int(resume_data.get('bot_ffa_endgame_retaliation_target', '-1'))
    rawKills = resume_data.get('bot_ffa_endgame_direct_kill_targets', '')
    state.direct_kill_targets = frozenset(
        int(part) for part in rawKills.split(',') if part.strip())
