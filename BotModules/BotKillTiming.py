from __future__ import annotations

from dataclasses import dataclass
import typing

import logbook
from Models import Move
from Path import Path
from base.client.map import Tile
from BotModules.BotGatherOps import BotGatherOps
from BotModules.BotPathingUtils import BotPathingUtils
from BotModules.BotRepetition import BotRepetition
from BotModules.BotTargeting import BotTargeting


if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot


@dataclass(slots=True)
class AllInKillEstimate:
    path: Path
    path_attack_value: int
    support_attack_value: int
    line_bonus_attack_value: int
    total_attack_value: int
    enemy_general_estimate: int
    remaining_cycle_turns: int
    inter_general_distance: int

    @property
    def is_viable(self) -> bool:
        return self.total_attack_value > self.enemy_general_estimate


class BotKillTiming:
    @staticmethod
    def get_projected_loss_all_in_move(bot: EklipZBot, defenseCriticalTileSet: typing.Set[Tile]) -> Move | None:
        if not bot.win_condition_analyzer.projected_loss_all_in_active:
            return None

        altEnemyGeneralPositions = bot.alt_en_gen_positions[bot.targetPlayer]
        if len(altEnemyGeneralPositions) > 6:
            bot.info(f'Skipping WCA projected-loss all-in gather because targetPlayer {bot.targetPlayer} has {len(altEnemyGeneralPositions)} alt enemy general positions')
            return None

        if bot.targetPlayerExpectedGeneralLocation is not None and bot.win_condition_analyzer.projected_loss_all_in_target != bot.targetPlayerExpectedGeneralLocation:
            bot.info(f'Updating WCA projected-loss all-in target from {bot.win_condition_analyzer.projected_loss_all_in_target} to {bot.targetPlayerExpectedGeneralLocation}')
            bot.win_condition_analyzer.projected_loss_all_in_target = bot.targetPlayerExpectedGeneralLocation

        target = bot.win_condition_analyzer.projected_loss_all_in_target
        if target is None:
            return None

        bot.curPath = None
        with bot.perf_timer.begin_move_event('WCA projected-loss all-in gather'):
            allInMove, valueGathered, turnsUsed, gatherNodes = BotGatherOps.get_gather_to_target_tiles(
                bot,
                [target],
                0.05,
                bot._map.remainingCycleTurns + 5,
                defenseCriticalTileSet,
                targetArmy=1,
                useTrueValueGathered=False,
                includeGatherTreeNodesThatGatherNegative=True,
                maximizeArmyGatheredPerTurn=True,
                priorityMatrix=BotGatherOps.get_gather_tiebreak_matrix(bot),
                shouldLog=True,
            )

        if allInMove is not None and not BotRepetition.detect_repetition(bot, allInMove):
            bot.info(f'Pass thru WCA projected-loss all-in gather! {allInMove} target {target} value {valueGathered} turns {turnsUsed}')
            bot.gatherNodes = gatherNodes
            return allInMove

        allInPath = BotKillTiming._get_all_in_path(bot)
        if allInPath is not None and allInPath.length <= bot._map.remainingCycleTurns:
            fallbackMove = allInPath.get_first_move()
            if fallbackMove is not None and not BotRepetition.detect_repetition(bot, fallbackMove):
                bot.info(f'Pass thru WCA projected-loss all-in fallback path! {fallbackMove} {allInPath}')
                return fallbackMove

        return None

    @staticmethod
    def find_all_in_option(bot: EklipZBot) -> Path | None:
        if bot.targetPlayer == -1:
            return None

        if bot.targetPlayerExpectedGeneralLocation is None:
            return None

        path = BotKillTiming._get_all_in_path(bot)
        if path is None:
            logbook.info(f'ALL_IN_KILL_TIMING turn={bot._map.turn} no_path targetPlayer={bot.targetPlayer}')
            return None

        estimate = BotKillTiming._estimate_all_in_kill(bot, path)
        logbook.info(
            f'ALL_IN_KILL_TIMING turn={bot._map.turn} path={path} '
            f'pathAttack={estimate.path_attack_value} supportAttack={estimate.support_attack_value} '
            f'lineBonusAttack={estimate.line_bonus_attack_value} totalAttack={estimate.total_attack_value} '
            f'enemyGeneralEstimate={estimate.enemy_general_estimate} '
            f'remainingCycleTurns={estimate.remaining_cycle_turns} interGeneralDistance={estimate.inter_general_distance} '
            f'viable={estimate.is_viable}'
        )

        if not estimate.is_viable:
            return None

        return path

    @staticmethod
    def _get_all_in_path(bot: EklipZBot) -> Path | None:
        path = BotTargeting.get_path_to_target_player(bot, isAllIn=True, cutLength=None, fromTile=bot.general)
        if path is not None:
            return path

        return BotPathingUtils.get_path_to_target(
            bot,
            bot.targetPlayerExpectedGeneralLocation,
            skipEnemyCities=True,
            preferNeutral=False,
            fromTile=bot.general,
            preferEnemy=False,
            avoidEnemyVision=True,
        )

    @staticmethod
    def _estimate_all_in_kill(bot: EklipZBot, path: Path) -> AllInKillEstimate:
        remainingCycleTurns = bot._map.remainingCycleTurns
        interGeneralDistance = path.length

        targetPlayer = bot.win_condition_analyzer.target_player
        targetTeam = bot.opponent_tracker._team_lookup_by_player[targetPlayer]
        logbook.warn(
            f'ALL_IN_KILL_TIMING_TARGET_CONTEXT '
            f'botPlayer={bot.player.index} botTargetPlayer={bot.targetPlayer} '
            f'wcaTargetPlayer={bot.win_condition_analyzer.target_player} '
            f'targetTeam={targetTeam} '
            f'teamCycleStatsIsNone={bot.opponent_tracker.current_team_cycle_stats[targetTeam] is None} '
            f'teamIndexes={bot.opponent_tracker._team_indexes} '
            f'teamIdsByPlayer={bot._map.team_ids_by_player_index}'
        )
        enemyGeneralEstimate = bot.opponent_tracker.get_fog_city_risk_in_turns_by_cycle_behavior(
            targetPlayer,
            inTurns=max(0, path.length),
            cityLimit=1,
        )

        pathAttackValue = BotKillTiming._estimate_path_attack_value(bot, path)
        supportAttackValue = BotKillTiming._estimate_near_path_support_attack_value(bot, path)
        lineBonusAttackValue = BotKillTiming._estimate_post_bonus_line_attack_value(bot, path, remainingCycleTurns)
        totalAttackValue = pathAttackValue + supportAttackValue + lineBonusAttackValue

        return AllInKillEstimate(
            path=path,
            path_attack_value=pathAttackValue,
            support_attack_value=supportAttackValue,
            line_bonus_attack_value=lineBonusAttackValue,
            total_attack_value=totalAttackValue,
            enemy_general_estimate=enemyGeneralEstimate,
            remaining_cycle_turns=remainingCycleTurns,
            inter_general_distance=interGeneralDistance,
        )

    @staticmethod
    def _estimate_path_attack_value(bot: EklipZBot, path: Path) -> int:
        attackValue = 0
        for tile in path.tileList:
            if tile == bot.targetPlayerExpectedGeneralLocation:
                continue
            if bot._map.is_tile_friendly(tile):
                attackValue += max(0, tile.army - 1)
            elif not tile.isObstacle:
                attackValue -= tile.army
        return max(0, attackValue)

    @staticmethod
    def _estimate_near_path_support_attack_value(bot: EklipZBot, path: Path) -> int:
        supportTiles: typing.Set[Tile] = set()
        candidateTiles = path.adjacentSet.difference(path.tileSet)
        for tile in candidateTiles:
            if tile == bot.targetPlayerExpectedGeneralLocation:
                continue
            if bot._map.is_tile_friendly(tile) and tile.army > 1:
                supportTiles.add(tile)

        supportAttackValue = 0
        for tile in supportTiles:
            supportAttackValue += max(0, tile.army - 1)
        return supportAttackValue

    @staticmethod
    def _estimate_post_bonus_line_attack_value(bot: EklipZBot, path: Path, remainingCycleTurns: int) -> int:
        if path.length > remainingCycleTurns:
            return 0

        lineAttackValue = 0
        # Tests/test_BotBehavior.py::test_should_detect_lost_round_and_detect_all_in_opportunity_and_set_up_all_in_instead expects the all-in evaluation to account for the post-bonus owned attack line of 2s that can make the second rally into the enemy general lethal.
        for tile in path.tileList:
            if tile == bot.general or tile == bot.targetPlayerExpectedGeneralLocation:
                continue
            lineAttackValue += 1
        return lineAttackValue
