from __future__ import annotations

import typing
from dataclasses import dataclass

import BotModules as BM
import logbook
import SearchUtils
from base.client.map import Tile
import typing


if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot


@dataclass(slots=True)
class InferredGeneralClearKillCandidate:
    """
    Viable inferred-general clear-kill evaluation for one enemy whose general location is
    unknown, produced by BotStateQueries._eval_inferred_general_clear_kill. Carries the found
    attack path stats plus the conservative hunt budget derived from how far the enemy's
    remaining valid-general region extends past that path, so
    get_ffa_clear_kill_enemy_player can pick the best opportunity deterministically.
    """
    player_index: int
    path_length: int
    path_value: float
    fog_risk: int
    candidate_count: int
    hunt_turns: int
    max_extra_distance: int


class BotStateQueries:
    @staticmethod
    def is_all_in(bot: EklipZBot):
        return bot.is_all_in_losing or bot.is_all_in_army_advantage or bot.all_in_city_behind

    @staticmethod
    def is_cyclic_winning_gather_viable(bot: EklipZBot) -> bool:
        """True while the cyclic winning gather (BotCombatOps.try_get_cyclic_all_in_move)
        can produce the timed attack gather: the latched cyclic mode, or currently
        winning on economy + tiles + army."""
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # a forced FFA endgame all-in must never defer to the target-only cyclic gather.
        if BM.BotFfaEndgame.is_forced_all_in(bot):
            return False
        if bot.is_winning_gather_cyclic:
            return True
        if bot.targetPlayer == -1:
            return False
        return (bot.opponent_tracker.winning_on_economy(byRatio=1.15)
                and bot.opponent_tracker.winning_on_tiles(byRatio=1.1)
                and bot.opponent_tracker.winning_on_army(byRatio=1.45))

    @staticmethod
    def is_timed_all_in_or_cyclic_active(bot: EklipZBot) -> bool:
        """Tests/test_AllIn.py::AllInTests.test_should_keep_timed_all_in_over_far_gathers
        True while a timed attack plan is (or should be) driving move selection, so
        unrelated gather systems (FORCE_FAR_GATHERS) must not hijack the pipeline:
        any all-in state, a running army-advantage temp all-in (the counter persists
        while the per-turn flag flickers off between determine_should_winning_all_in
        evaluations), or a viable cyclic winning gather."""
        return (BotStateQueries.is_all_in(bot)
                or bot.all_in_army_advantage_counter > 0
                or BotStateQueries.is_cyclic_winning_gather_viable(bot))

    @staticmethod
    def is_tile_enemy(bot: EklipZBot, tile: Tile) -> bool:
        """Check if a tile belongs to an enemy player."""
        return tile is not None and tile.player != -1 and tile.player != bot.general.player and bot._map.is_tile_enemy(tile)

    @staticmethod
    def is_ffa_exclusive_targeting_active(bot: EklipZBot) -> bool:
        """
        Tests/test_FFA.py::test_should_not_attack_unprovoked_enemies_in_early_ffa
        Tests/test_FFA.py::test_should_exclusively_attack_player_that_attacks_us_in_early_ffa
        In a non-dominant FFA where multiple distinct enemy players have revealed territory, the bot
        must refuse to opportunistically attack: only players actively attacking us
        (is_player_aggressive / aggression_factor > 120), players who left the game, or a single
        enemy we can clearly kill (which becomes the exclusive locked target) may be attacked.
        Tiles of unattackable players may still be CROSSED only as part of a path to attack the
        locked target; expansion/gather/leaf/city-kill moves may never capture them.
        @param bot:
        @return:
        """
        if not BotStateQueries.is_still_ffa_and_non_dominant(bot):
            return False

        revealedCount = 0
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates:
                continue
            if len(player.tiles) > 0:
                revealedCount += 1

        return revealedCount >= 2

    @staticmethod
    def get_ffa_clear_kill_enemy_player(bot: EklipZBot) -> int:
        """
        Returns the one enemy player we can clearly kill right now while exclusive targeting is
        active: their general location is known, we have a decisive standing-army advantage over
        them, and their general is reachable within ~12 turns. -1 if nobody qualifies.

        Tests/test_FFA.py::test_should_snap_kill_nearby_ffa_general_after_enemy_army_loss: enemies
        whose general location is UNKNOWN but who are still seen and alive also qualify when their
        remaining valid-general region is small and can be hunted inside a conservative 10-turn
        army budget - see _eval_inferred_general_clear_kill. A known-general clear kill keeps
        priority; the inferred branch only fills the gap for enemies the bot cannot yet pinpoint.
        @param bot:
        @return:
        """
        bestPlayer = -1
        bestArmyRatio = 1.3
        inferredBest: InferredGeneralClearKillCandidate | None = None
        ourStats = bot._map.get_team_stats(bot._map.player_index)
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            enGen = bot._map.generals[player.index]
            if enGen is not None and enGen.isGeneral:
                enStats = bot._map.get_team_stats(player.index)
                if enStats.standingArmy <= 0:
                    continue
                armyRatio = ourStats.standingArmy / enStats.standingArmy
                genDist = bot._map.get_distance_between(bot.general, enGen)
                if genDist > 12:
                    continue
                if armyRatio >= bestArmyRatio:
                    bestArmyRatio = armyRatio
                    bestPlayer = player.index
                continue

            inferred = BotStateQueries._eval_inferred_general_clear_kill(bot, player.index)
            if inferred is None:
                continue
            if inferredBest is None:
                inferredBest = inferred
                continue
            inferredKey = (inferred.hunt_turns, inferred.path_length, -inferred.path_value, inferred.player_index)
            bestKey = (inferredBest.hunt_turns, inferredBest.path_length, -inferredBest.path_value, inferredBest.player_index)
            if inferredKey < bestKey:
                inferredBest = inferred

        if bestPlayer != -1:
            return bestPlayer
        if inferredBest is not None:
            logbook.info(
                f'FFA_CLEAR_KILL inferred p{inferredBest.player_index} ({bot._map.usernames[inferredBest.player_index]}): '
                f'pathLen={inferredBest.path_length} pathVal={inferredBest.path_value:.1f} '
                f'maxExtraDist={inferredBest.max_extra_distance} huntTurns={inferredBest.hunt_turns} '
                f'fogRisk@{inferredBest.hunt_turns}t={inferredBest.fog_risk} candidates={inferredBest.candidate_count}')
            return inferredBest.player_index
        return -1

    @staticmethod
    def _eval_inferred_general_clear_kill(bot: EklipZBot, playerIndex: int) -> InferredGeneralClearKillCandidate | None:
        """
        Tests/test_FFA.py::test_should_snap_kill_nearby_ffa_general_after_enemy_army_loss
        UnitTests/test_FfaClearKill.py: evaluates an alive, seen enemy whose general location
        is unknown as an FFA clear-kill candidate. The enemy's remaining valid-general region
        (ArmyTracker.valid_general_positions_by_player) must be nonempty and at most 12 tiles,
        a friendly stack >5 must sit within manhattan 10 of some candidate, and a real
        assembled-force path to the region must exist. The region must also be localized
        enough to hunt inside a conservative 10-turn budget: huntTurns =
        path.length + 2*maxExtraDistance, where maxExtraDistance is the farthest any candidate
        sits from the found path; the projected fog army risk is evaluated at huntTurns and
        the path's army must still exceed it after paying 2*maxExtraDistance army for the
        diversion, so broad, scattered, or unreachable regions cannot qualify.
        @param bot:
        @param playerIndex: enemy player index with unknown general location.
        @return: InferredGeneralClearKillCandidate or None if not viable.
        """
        candidates = [t for t in bot.armyTracker.valid_general_positions_by_player[playerIndex]]
        if len(candidates) == 0 or len(candidates) > 12:
            return None

        hasNearbyStack = False
        for stack in bot._map.players[bot.general.player].tiles:
            if stack.army <= 5:
                continue
            for candidate in candidates:
                if abs(stack.x - candidate.x) + abs(stack.y - candidate.y) <= 10:
                    hasNearbyStack = True
                    break
            if hasNearbyStack:
                break
        if not hasNearbyStack:
            return None

        fogRiskNow = bot.opponent_tracker.get_approximate_fog_army_risk(playerIndex, inTurns=0)
        path = SearchUtils.dest_breadth_first_target(
            bot._map,
            candidates,
            targetArmy=max(1, fogRiskNow),
            maxTime=0.01,
            maxDepth=10,
            searchingPlayer=bot.general.player,
            additionalIncrement=0.5,
            noLog=True)
        if path is None or path.length <= 0 or path.length > 10:
            return None

        maxExtraDistance = 0
        for candidate in candidates:
            closestDist = None
            for pathTile in path.tileList:
                dist = bot._map.get_distance_between_or_none(candidate, pathTile)
                if dist is not None and (closestDist is None or dist < closestDist):
                    closestDist = dist
            if closestDist is None:
                return None
            if closestDist > maxExtraDistance:
                maxExtraDistance = closestDist

        huntTurns = path.length + 2 * maxExtraDistance
        if huntTurns > 10:
            return None

        fogRiskAtKill = bot.opponent_tracker.get_approximate_fog_army_risk(playerIndex, inTurns=huntTurns)
        if path.value - 2 * maxExtraDistance <= max(0, fogRiskAtKill):
            return None

        return InferredGeneralClearKillCandidate(
            player_index=playerIndex,
            path_length=path.length,
            path_value=path.value,
            fog_risk=fogRiskAtKill,
            candidate_count=len(candidates),
            hunt_turns=huntTurns,
            max_extra_distance=maxExtraDistance)

    @staticmethod
    def update_ffa_exclusive_target_lock(bot: EklipZBot) -> None:
        """
        Maintains bot.ffa_exclusive_target_lock: the enemy player we are committed to attacking
        exclusively while is_ffa_exclusive_targeting_active holds. Sticky per
        Tests/test_FFA.py::test_should_exclusively_attack_player_that_attacks_us_in_early_ffa:
        once locked we stay on that player until they die or the FFA-pacifist gate ends, so
        aggression_factor decay mid-war cannot release the lock. The strongest current aggressor
        is preferred; otherwise a clear-kill candidate is locked so we target that player only.
        @param bot:
        @return:
        """
        if not BotStateQueries.is_ffa_exclusive_targeting_active(bot):
            if bot.ffa_exclusive_target_lock != -1:
                logbook.info(f'FFA_EXCL unlock p{bot.ffa_exclusive_target_lock} ({bot._map.usernames[bot.ffa_exclusive_target_lock]}): pacifist gate ended')
                bot.ffa_exclusive_target_lock = -1
            return

        if bot.ffa_exclusive_target_lock != -1:
            if bot._map.players[bot.ffa_exclusive_target_lock].dead:
                logbook.info(f'FFA_EXCL unlock p{bot.ffa_exclusive_target_lock} ({bot._map.usernames[bot.ffa_exclusive_target_lock]}): locked player died')
                bot.ffa_exclusive_target_lock = -1
            else:
                return

        bestAggro = -1
        bestAggroFactor = 120
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            if BM.BotTimings.BotTimings.is_player_aggressive(bot, player.index) and player.aggression_factor > bestAggroFactor:
                bestAggroFactor = player.aggression_factor
                bestAggro = player.index
        if bestAggro != -1:
            bot.ffa_exclusive_target_lock = bestAggro
            logbook.info(f'FFA_EXCL locked p{bestAggro} ({bot._map.usernames[bestAggro]}): attacking us, aggro {bestAggroFactor}')
            return

        clearKill = BotStateQueries.get_ffa_clear_kill_enemy_player(bot)
        if clearKill != -1:
            bot.ffa_exclusive_target_lock = clearKill
            logbook.info(f'FFA_EXCL locked p{clearKill} ({bot._map.usernames[clearKill]}): clear kill candidate')

    @staticmethod
    def get_ffa_unattackable_players(bot: EklipZBot) -> typing.Set[int] | None:
        """
        Returns the set of revealed enemy player indexes whose tiles may NOT be attacked while
        is_ffa_exclusive_targeting_active holds, or None when the restriction does not apply.
        Attackable: the exclusive locked target, players actively attacking us, and players that
        left the game (free kills per Tests/test_FFA.py FFA pacifism tests).
        @param bot:
        @return:
        """
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # forced endgame modes restrict attacks to the policy target (or nobody while
        # TURTLE) regardless of the exclusive-targeting pacifism state; unseen enemies count.
        ffaEndgameMode = BM.BotFfaEndgame.get_mode(bot)
        if ffaEndgameMode in (BM.BotFfaEndgame.FfaEndgameMode.ALL_IN, BM.BotFfaEndgame.FfaEndgameMode.RETALIATE):
            return BotStateQueries._ffa_endgame_unattackable_except(
                bot, BM.BotFfaEndgame.get_state(bot).decision.target_player)
        if ffaEndgameMode == BM.BotFfaEndgame.FfaEndgameMode.TURTLE:
            return BotStateQueries._ffa_endgame_unattackable_except(bot, -1)

        if not BotStateQueries.is_ffa_exclusive_targeting_active(bot):
            return None

        attackable = set()
        if bot.ffa_exclusive_target_lock != -1:
            attackable.add(bot.ffa_exclusive_target_lock)
        afkPlayers = BM.BotTargeting.BotTargeting.get_afk_players(bot)
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            if player.leftGame or player in afkPlayers or BM.BotTimings.BotTimings.is_player_aggressive(bot, player.index):
                attackable.add(player.index)

        unattackable = set()
        for player in bot._map.players:
            if player.dead or player.index == bot._map.player_index or player.index in bot._map.teammates or len(player.tiles) == 0:
                continue
            if player.index not in attackable:
                unattackable.add(player.index)
        return unattackable

    @staticmethod
    def _ffa_endgame_unattackable_except(bot: EklipZBot, attackableTarget: int) -> typing.Set[int]:
        """Enemy player indexes that may not be attacked under forced FFA endgame modes."""
        unattackable: typing.Set[int] = set()
        selfIndex = bot.general.player
        teamIds = bot._map.team_ids_by_player_index
        ourTeam = teamIds[selfIndex] if selfIndex < len(teamIds) else selfIndex
        for player in bot._map.players:
            if player.dead or player.index == selfIndex or player.index in bot._map.teammates:
                continue
            if player.index < len(teamIds) and teamIds[player.index] == ourTeam:
                continue
            if player.index != attackableTarget:
                unattackable.add(player.index)
        return unattackable

    @staticmethod
    def get_ffa_unattackable_tiles(bot: EklipZBot) -> typing.Set[Tile]:
        """
        All tiles currently owned by get_ffa_unattackable_players. For negativeTiles/skipTiles
        inputs of non-attack searches (expansion plans, econ gathers, leaf captures) so they can
        neither capture nor path through unattackable enemy land. Empty set when inactive.
        @param bot:
        @return:
        """
        unattackable = BotStateQueries.get_ffa_unattackable_players(bot)
        if not unattackable:
            return set()
        return set(t for t in bot._map.pathable_tiles if t.player in unattackable)

    @staticmethod
    def is_tile_ffa_unattackable(bot: EklipZBot, tile: Tile) -> bool:
        """
        @param bot:
        @param tile:
        @return: True when tile belongs to a revealed enemy we may not attack under FFA exclusive targeting.
        """
        if tile is None or tile.player < 0:
            return False
        unattackable = BotStateQueries.get_ffa_unattackable_players(bot)
        return unattackable is not None and tile.player in unattackable

    @staticmethod
    def is_still_ffa_and_non_dominant(bot: EklipZBot) -> bool:
        # Tests/test_FFA.py::FFATests.test_should_nonstop_all_in_weaker_player_when_three_left
        # forced endgame modes override the buggy dominance scan: ALL_IN/RETALIATE report
        # non-FFA-non-dominant so all-in/stealth machinery engages; TURTLE stays pacifist.
        ffaEndgameMode = BM.BotFfaEndgame.get_mode(bot)
        if ffaEndgameMode in (BM.BotFfaEndgame.FfaEndgameMode.ALL_IN, BM.BotFfaEndgame.FfaEndgameMode.RETALIATE):
            return False
        if ffaEndgameMode == BM.BotFfaEndgame.FfaEndgameMode.TURTLE:
            return True

        isFfa = False
        if bot._map.remainingPlayers > 2 and not bot._map.is_2v2:
            isFfa = True

        if not isFfa:
            return False

        dominating = 0
        nearEven = bot._map.remainingPlayers - 1
        dominatedBy = 0
        for player in bot._map.players:
            if player == bot.general.player:
                continue

            if bot.opponent_tracker.winning_on_army(byRatio=1.2, againstPlayer=player.index, offset=-10, useFullArmy=True):
                dominating += 1
                nearEven -= 1
            elif not bot.opponent_tracker.winning_on_army(byRatio=0.9, againstPlayer=player.index, useFullArmy=True):
                dominatedBy += 1
                nearEven -= 1

        if dominating > dominatedBy:
            return False

        return True

    @staticmethod
    def get_intergeneral_analysis(bot: EklipZBot):
        return bot.board_analysis.intergeneral_analysis

    @staticmethod
    def get_player_army_amount_on_path(bot: EklipZBot, path, player: int, startIdx=0, endIdx=1000):
        value = 0
        idx = 0
        pathNode = path.start
        while pathNode is not None:
            if bot._map.is_player_on_team_with(pathNode.tile.player, player) and startIdx <= idx <= endIdx:
                value += (pathNode.tile.army - 1)
            pathNode = pathNode.next
            idx += 1
        return value

    @staticmethod
    def get_player_army_amount_on_tiles(bot: EklipZBot, tiles: typing.Iterable[Tile], player: int):
        value = 0
        for tile in tiles:
            if bot._map.is_player_on_team_with(tile.player, player):
                value += (tile.army - 1)
        return value

    @staticmethod
    def get_target_army_inc_adjacent_enemy(bot: EklipZBot, tile) -> int:
        sumAdj = 0
        for adj in tile.adjacents:
            if BotStateQueries.is_tile_enemy(bot, adj):
                sumAdj += adj.army - 1
        armyToSearch = sumAdj
        return armyToSearch

    @staticmethod
    def get_target_army_inc_adjacent_enemy_and_tiles(bot: EklipZBot, tile) -> typing.Tuple[int, typing.Set[Tile]]:
        sumAdj = 0
        adjTiles = set()
        for adj in tile.adjacents:
            if BotStateQueries.is_tile_enemy(bot, adj):
                if adj.army > 1:
                    sumAdj += adj.army - 1
                    adjTiles.add(adj)
        armyToSearch = sumAdj
        return armyToSearch, adjTiles

    @staticmethod
    def parse_tile_str(bot: EklipZBot, tileStr: str):
        xStr, yStr = tileStr.split(',')
        return bot._map.GetTile(int(xStr), int(yStr))

    @staticmethod
    def parse_bool(bot: EklipZBot, boolStr: str) -> bool:
        return boolStr.lower().strip() == "true"

    @staticmethod
    def str_tiles(bot: EklipZBot, tiles) -> str:
        return '|'.join([str(t) for t in tiles])

    @staticmethod
    def get_army_at(bot: EklipZBot, tile: Tile, no_expected_path: bool = False):
        return bot.armyTracker.get_or_create_army_at(tile, skip_expected_path=no_expected_path)

    @staticmethod
    def get_army_at_x_y(bot: EklipZBot, x: int, y: int):
        tile = bot._map.GetTile(x, y)
        return BotStateQueries.get_army_at(bot, tile)

    @staticmethod
    def get_n_closest_team_tiles_near(bot: EklipZBot, nearTiles: typing.List[Tile], player: int, distance: int, limit: int, includeNeutral: bool = False) -> typing.List[Tile]:
        tiles = set(nearTiles)

        def nearbyTileAdder(tile: Tile) -> bool:
            if len(tiles) > limit:
                return True

            if bot._map.is_tile_on_team_with(tile, player) or (includeNeutral and tile.isNeutral and tile.army == 0 and not tile.isObstacle):
                tiles.add(tile)

            return False

        SearchUtils.breadth_first_foreach(bot._map, nearTiles, distance, foreachFunc=nearbyTileAdder)

        return [t for t in tiles]


BM.BotStateQueries = BotStateQueries
