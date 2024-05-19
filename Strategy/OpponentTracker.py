from __future__ import annotations

import logbook
import typing

from ArmyTracker import Army
from StrategyModels import CycleStatsData, PlayerMoveCategory
from ViewInfo import ViewInfo, TargetStyle
from base.client.map import MapBase, TeamStats, Tile, Player, PLAYER_CHAR_BY_INDEX

ENABLE_DEBUG_ASSERTS = False


class FogGatherQueue(object):
    def __init__(self, player: int):
        self.player: int = player

        self.length: int = 0
        """The number of fog tiles the player has in queue. Includes 1s."""

        self.gatherable_length: int = 0
        """The number of gatherable fog tiles the player has in queue. So excludes 1's and 0's."""

        self.total_sum: int = 0
        """The sum of all ungathered fog army tile amounts"""

        # self._gather_amts: typing.Dict[int, int] = {}
        self._gather_amts: typing.List[int] = []
        self._gather_amt_max: int = 0

    def get_amount_dict(self) -> typing.Dict[int, int]:
        return {size: amount for size, amount in enumerate(self._gather_amts) if amount > 0}

    def get_amount_list(self) -> typing.Tuple[int, typing.List[int]]:
        """Returns maxSize, sizeIndexingToCountList"""
        return self._gather_amt_max, self._gather_amts.copy()

    def set_amount_for_size(self, tileSize: int, numTiles: int):
        existingAmt = self.get_or_create_count(tileSize)
        if existingAmt == numTiles:
            return

        self.total_sum -= tileSize * existingAmt
        self.total_sum += tileSize * numTiles

        self._gather_amts[tileSize] = numTiles

        if numTiles > 0:
            if tileSize > self._gather_amt_max:
                self._gather_amt_max = tileSize
        else:
            if self._gather_amt_max == tileSize:
                self._gather_amt_max = self.find_next_max_amount_under(tileSize)

    def append(self, tileSize: int):
        if tileSize > self._gather_amt_max:
            self.get_or_create_count(tileSize)
            self._gather_amt_max = tileSize

        self._gather_amts[tileSize] += 1
        self.total_sum += tileSize
        self.length += 1
        if tileSize > 1:
            self.gatherable_length += 1

    def increment_army_bonus(self):
        if self.length == 0:
            return

        self._gather_amt_max += 1
        self.gatherable_length += self._gather_amts[1]

        self.get_or_create_count(self._gather_amt_max)
        for i in range(self._gather_amt_max, 0, -1):
            self._gather_amts[i] = self._gather_amts[i - 1]

        self._gather_amts[0] = 0
        # length doesn't change. Total sum increases by the number of tiles we have here, though.
        self.total_sum += self.length

    def pop_next_highest(self, leaveOne: bool = True) -> int:
        """Pops and returns the next highest, and leaves a 1 behind. Returns None if there are no gatherable amounts. Returns the raw value, not adjusted for the 1 left behind."""
        if self._gather_amt_max == 0:
            return 0

        amtLeft = self._gather_amts[self._gather_amt_max]
        if amtLeft <= 0:
            raise AssertionError(f'_gather_amt_max was {self._gather_amt_max}, however the count for that tile is {amtLeft}... Should never happen. Something is not correctly adjusting _gather_amt_max.')

        if leaveOne:
            self.append(1)

        oldMax = self._gather_amt_max
        self.remove_queued_gather_for_exact_unchecked(oldMax)

        return oldMax

    def peek_next_highest(self) -> int:
        """Not adjusted for the 1 army that would be left behind if gathered."""
        return self._gather_amt_max

    def remove_queued_gather_closest_to_amount(self, tileAmount: int, leaveOne: bool) -> int:
        """Returns the amount that was actually removed."""
        if self.length == 0:
            return 0

        bestMax = min(self._gather_amt_max, tileAmount)
        bestMin = bestMax - 1

        maxValid = bestMax <= self._gather_amt_max
        minValid = bestMin > -1
        toRemove = self._gather_amt_max

        while maxValid or minValid:
            if maxValid:
                amt = self._gather_amts[bestMax]
                if amt > 0:
                    toRemove = bestMax
                    break
            if minValid:
                amt = self._gather_amts[bestMin]
                if amt > 0:
                    toRemove = bestMax
                    break

            bestMax += 1
            bestMin -= 1
            maxValid = bestMax <= self._gather_amt_max
            minValid = bestMin > -1

        if toRemove != tileAmount:
            logbook.info(
                f'RemoveGath: p{self.player} didnt have tile of tileAmount {tileAmount}, dropping {toRemove} from queue instead...?')

        minActionable = 1 if leaveOne else -1
        if toRemove > minActionable:
            self.remove_queued_gather_for_exact_unchecked(toRemove)
            if leaveOne:
                self.append(1)

        return toRemove

    def try_remove_queued_gather_for_exact_amount(self, tileAmount: int, leaveOne: bool) -> bool:
        if tileAmount > self._gather_amt_max:
            return False
        amt = self._gather_amts[tileAmount]
        if not amt:
            return False

        self.remove_queued_gather_for_exact_unchecked(toRemoveSize=tileAmount)
        if leaveOne:
            self.append(1)

        return True

    def as_tile_list(self, includeOnesAndZeros: bool = False) -> typing.List[int]:
        """Returns a list of gatherable tile amounts in order from largest to smallest."""
        l = []
        minAmt = 1
        if includeOnesAndZeros:
            minAmt = -1
        for tileSize in range(self._gather_amt_max, minAmt, -1):
            amt = self._gather_amts[tileSize]
            if not amt:
                continue

            l.extend(tileSize for _ in range(amt))

        return l

    def get_count(self, tileSize: int) -> int:
        if tileSize >= len(self._gather_amts):
            return 0

        return self._gather_amts[tileSize]

    def get_or_create_count(self, tileSize: int) -> int:
        while tileSize >= len(self._gather_amts):
            self._gather_amts.append(0)

        return self._gather_amts[tileSize]

    def find_next_max_amount_under(self, tileSize: int) -> int:
        tileSize = tileSize - 1
        nextMaxSize = 0
        while tileSize > -1:
            if self._gather_amts[tileSize] > 0:
                nextMaxSize = tileSize
                break
            tileSize -= 1

        return nextMaxSize

    def remove_queued_gather_for_exact_unchecked(self, toRemoveSize: int):
        amt = self._gather_amts[toRemoveSize]
        self.length -= 1
        if toRemoveSize > 1:
            self.gatherable_length -= 1
        self._gather_amts[toRemoveSize] = amt - 1
        self.total_sum -= toRemoveSize

        if amt == 1 and toRemoveSize == self._gather_amt_max:
            self._gather_amt_max = self.find_next_max_amount_under(self._gather_amt_max)


class OpponentTracker(object):
    def __init__(self, map: MapBase, viewInfo: ViewInfo | None = None):
        self.outbound_emergence_notifications: typing.List[typing.Callable[[int, Tile, bool], None]] = []
        self.map: MapBase = map
        self.team_score_data_history: typing.Dict[int, typing.Dict[int, TeamStats | None]] = {}
        self.targetPlayer: int = -1
        self.skip_this_turn: bool = False
        """Set to true when loading up a unit test so that the end of original turn stats are kept instead of running on top of those again."""

        self.current_team_scores: typing.Dict[int, TeamStats | None] = {}
        """Track the current (or during scan, last turn) data for diffing what happened since last turn"""

        self.last_team_scores: typing.Dict[int, TeamStats | None] = {}
        """Track the last (or during scan, two turns ago) data for diffing what happened since two turns ago, useful for things like city changes since army increments only tick on even turns."""

        self.team_cycle_stats_history: typing.Dict[int, typing.Dict[int, CycleStatsData | None]] = {}

        self.current_team_cycle_stats: typing.Dict[int, CycleStatsData] = {}

        self.assumed_player_average_tile_values: typing.List[float] = [0.0 for _ in map.players]
        self.assumed_player_average_tile_values.append(0.0)

        """The assumed average value of land the player owns, used when looking at attacks that happen against the player in the fog, whether by us or someone else."""

        self.last_player_move_type: typing.Dict[int, PlayerMoveCategory] = {}

        rawTeams = self.map.teams
        if rawTeams is None:
            rawTeams = [i for i, p in enumerate(self.map.players)]

        self._team_indexes = []

        self._team_lookup_by_player: typing.List[int] = MapBase.get_teams_array(map)
        self._players_lookup_by_team: typing.Dict[int, typing.List[int]] = {}

        self._gather_queues_new_by_player: typing.Dict[int, FogGatherQueue] = {}

        self._emergences: typing.List[typing.Tuple[Tile, int, int]] = []
        self._revealed: typing.Set[Tile] = set()
        self._moves_into_fog: typing.List[Army] = []
        self._vision_losses: typing.Set[Tile] = set()
        self.view_info: ViewInfo | None = viewInfo

        # lastCycleTurn = self.get_last_cycle_end_turn()

        for team in rawTeams:
            if team not in self.team_score_data_history:
                for player in self.map.players:
                    if rawTeams[player.index] == team:
                        playerList = self._players_lookup_by_team.get(team, [])
                        playerList.append(player.index)
                        self._players_lookup_by_team[team] = playerList
                        self.assumed_player_average_tile_values[player.index] = 1.0
                        self._gather_queues_new_by_player[player.index] = FogGatherQueue(player.index)
                        self.last_player_move_type[player.index] = PlayerMoveCategory.FogGather

                self.team_score_data_history[team] = {}
                teamPlayers = self.get_team_players(team)
                turn0Stats = CycleStatsData(team, teamPlayers)
                self.team_score_data_history[team][0] = TeamStats(0, 0, 0, len(turn0Stats.players), 0, 0, team, teamPlayers, teamPlayers, self.map.turn - 1)
                self.current_team_cycle_stats[team] = turn0Stats
                self.team_cycle_stats_history[team] = {}
                self._team_indexes.append(team)
                self.current_team_scores[team] = None
                self.last_team_scores[team] = None

    def analyze_turn(self, targetPlayer: int):
        self.current_differential_vs_us_by_team: typing.Dict[int, CycleStatsData]
        self.targetPlayer = targetPlayer

        for player in self.map.players:
            # if we don't figure out anything else, then probably a fog gather. Default to that at start of each turn.
            self.last_player_move_type[player.index] = PlayerMoveCategory.FogGather

        if self.skip_this_turn:
            self.skip_this_turn = False
            return

        for team in self._team_indexes:
            curTurnTeamScore = self.map.get_team_stats_by_team_id(team)

            teamStats = self.calculate_cycle_stats(team, curTurnTeamScore)
            self.current_team_cycle_stats[team] = teamStats

            if self.map.turn == 2:
                # fake the turn 0 data so we can do stuff in first cycle still.
                curTurnTeamScore.score -= curTurnTeamScore.cityCount
                self.team_score_data_history[team][0] = curTurnTeamScore

                curTurnTeamScore = self.map.get_team_stats_by_team_id(team)

            elif self.map.turn % 50 == 0:
                self.begin_next_cycle(curTurnTeamScore, team, teamStats)

            self.last_team_scores[team] = self.current_team_scores[team]
            self.current_team_scores[team] = curTurnTeamScore

        self._emergences = []
        self._moves_into_fog = []
        self._revealed = set()
        self._vision_losses = set()

        self.recalculate_average_tile_values()

    def begin_next_cycle(self, curTurnTeamScore: TeamStats, team: int, teamStats: CycleStatsData | None):
        # do the final pass on the current cycle data and then start a new cycle.
        self.team_score_data_history[team][self.map.turn] = curTurnTeamScore
        if teamStats is not None:
            self.team_cycle_stats_history[team][self.map.turn] = teamStats.clone()
            if self.map.turn > 99:
                oldTotal = teamStats.approximate_fog_army_available_total
                teamStats.approximate_fog_army_available_total = round(0.96 * teamStats.approximate_fog_army_available_total + 0.49)
                self.view_info.add_info_line(f'Updated team {team} approx fog army from {oldTotal} to {teamStats.approximate_fog_army_available_total} (true total {teamStats.approximate_fog_army_available_total_true})')

    def get_current_cycle_end_turn(self) -> int | None:
        """

        @return: The turn that the current cycle will end on.
        """
        remainingCycleTurns = 50 - self.map.turn % 50
        return self.map.turn + remainingCycleTurns

    def get_last_cycle_end_turn_raw(self, cyclesToGoBack: int = 0) -> int | None:
        """

        @param cyclesToGoBack: If greater than zero goes back that many EXTRA cycle ends.
        @return: The turn, or None if the turn is turn 0 or earlier.
        """

        cycleTurn = self.map.turn % 50
        if cycleTurn == 0:
            cyclesToGoBack += 1

        turn = self.map.turn - cycleTurn - 50 * cyclesToGoBack
        if turn < 0:
            return None

        return turn

    def get_last_cycle_end_turn(self, cyclesToGoBack: int = 0) -> int | None:
        """

        @param cyclesToGoBack: If greater than zero goes back that many EXTRA cycle ends.
        @return: The turn, or None if no data for that cycle OR if the turn is turn 0 or earlier.
        """

        turn = self.get_last_cycle_end_turn_raw(cyclesToGoBack)

        exampleTeamStats = self.team_score_data_history[self._team_indexes[0]]

        if exampleTeamStats.get(turn, None) is None:
            return None

        return turn

    def get_last_cycle_stats_per_team(self) -> typing.Dict[int, CycleStatsData]:
        lastCycleEndTurn = self.get_last_cycle_end_turn()
        ret = {}
        for team in self._team_indexes:
            lastCycleStats = self.team_cycle_stats_history[team].get(lastCycleEndTurn, None)
            ret[team] = lastCycleStats

        return ret

    def notify_emerged_army(self, tile: Tile, emergingPlayer: int, emergenceAmount: int):
        """
        Call this when an army emerges so that we can reduce the tracked expected fog gather amounts.

        @param tile:
        @param emergingPlayer:
        @param emergenceAmount:
        @return:
        """
        em = (tile, emergingPlayer, emergenceAmount)
        logbook.info(f'OppTrack EM: queued {repr(em)}')
        self._emergences.append(em)

    def notify_player_tile_revealed(self, tile: Tile):
        """
        Call this when a tile that was not previously owned by a team is revealed from fog as owned by that team.

        @param tile:
        @return:
        """
        logbook.info(f'OppTrack V+: queued {repr(tile)}')

        self._revealed.add(tile)

    def notify_player_tile_vision_lost(self, tile: Tile):
        if tile.player >= 0:
            logbook.info(f'OppTrack V-: queued {repr(tile)}')
            self._vision_losses.add(tile)

    def dump_to_string_data(self) -> str:
        data = []

        for team in self._team_indexes:
            stats = self.current_team_cycle_stats.get(team, None)
            if stats is not None:
                data.append(f'ot_{team}_stats_moves_spent_capturing_fog_tiles={stats.moves_spent_capturing_fog_tiles}')
                data.append(f'ot_{team}_stats_moves_spent_capturing_visible_tiles={stats.moves_spent_capturing_visible_tiles}')
                data.append(f'ot_{team}_stats_moves_spent_gathering_fog_tiles={stats.moves_spent_gathering_fog_tiles}')
                data.append(f'ot_{team}_stats_moves_spent_gathering_visible_tiles={stats.moves_spent_gathering_visible_tiles}')
                data.append(f'ot_{team}_stats_approximate_army_gathered_this_cycle={stats.approximate_army_gathered_this_cycle}')
                data.append(f'ot_{team}_stats_army_annihilated_visible={stats.army_annihilated_visible}')
                data.append(f'ot_{team}_stats_army_annihilated_fog={stats.army_annihilated_fog}')
                data.append(f'ot_{team}_stats_army_annihilated_total={stats.army_annihilated_total}')
                data.append(f'ot_{team}_stats_approximate_fog_army_available_total={stats.approximate_fog_army_available_total}')
                data.append(f'ot_{team}_stats_approximate_fog_army_available_total_true={stats.approximate_fog_army_available_total_true}')
                data.append(f'ot_{team}_stats_approximate_fog_city_army={stats.approximate_fog_city_army}')

        tileCountsByPlayer = self.get_all_player_fog_tile_count_dict()

        for player, tileCounts in tileCountsByPlayer.items():
            if player == self.map.player_index or player in self.map.teammates:
                continue
            playerFogSubtext = "|".join([f'{n}x{tileSize}' for tileSize, n in sorted(tileCounts.items(), reverse=True)])
            data.append(f'ot_{PLAYER_CHAR_BY_INDEX[player]}_tcs={playerFogSubtext}')

        for i in range(3):
            cycleTurn = self.get_last_cycle_end_turn(cyclesToGoBack=i)
            for team in self._team_indexes:
                score = self.team_score_data_history[team].get(cycleTurn, None)
                if score is not None:
                    data.append(f'ot_{team}_c_{cycleTurn}_tileCount={score.tileCount}')
                    data.append(f'ot_{team}_c_{cycleTurn}_score={score.score}')
                    data.append(f'ot_{team}_c_{cycleTurn}_standingArmy={score.standingArmy}')
                    data.append(f'ot_{team}_c_{cycleTurn}_cityCount={score.cityCount}')
                    data.append(f'ot_{team}_c_{cycleTurn}_fightingDiff={score.fightingDiff}')
                    data.append(f'ot_{team}_c_{cycleTurn}_unexplainedTileDelta={score.unexplainedTileDelta}')

                stats = self.team_cycle_stats_history[team].get(cycleTurn, None)
                if stats is not None:
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_moves_spent_capturing_fog_tiles={stats.moves_spent_capturing_fog_tiles}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_moves_spent_capturing_visible_tiles={stats.moves_spent_capturing_visible_tiles}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_moves_spent_gathering_fog_tiles={stats.moves_spent_gathering_fog_tiles}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_moves_spent_gathering_visible_tiles={stats.moves_spent_gathering_visible_tiles}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_approximate_army_gathered_this_cycle={stats.approximate_army_gathered_this_cycle}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_army_annihilated_visible={stats.army_annihilated_visible}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_army_annihilated_fog={stats.army_annihilated_fog}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_army_annihilated_total={stats.army_annihilated_total}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_army_available_total={stats.approximate_fog_army_available_total}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_army_available_total_true={stats.approximate_fog_army_available_total_true}')
                    data.append(f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_city_army={stats.approximate_fog_city_army}')

        return '\n'.join(data)

    def load_from_map_data(self, data: typing.Dict[str, str]):
        for i in range(5):
            cycleTurn = self.get_last_cycle_end_turn_raw(cyclesToGoBack=i)
            if cycleTurn is None:
                break
            for team in self._team_indexes:
                teamPlayers = self.get_team_players(team)
                teamScore = TeamStats(0, 0, 0, 0, 0, 0, team, teamPlayers, teamPlayers, 0)
                self.team_score_data_history[team][cycleTurn] = teamScore
                if f'ot_{team}_c_{cycleTurn}_tileCount' in data:
                    teamScore.tileCount = int(data[f'ot_{team}_c_{cycleTurn}_tileCount'])
                    teamScore.score = int(data[f'ot_{team}_c_{cycleTurn}_score'])
                    teamScore.standingArmy = int(data[f'ot_{team}_c_{cycleTurn}_standingArmy'])
                    teamScore.cityCount = int(data[f'ot_{team}_c_{cycleTurn}_cityCount'])
                    teamScore.fightingDiff = int(data[f'ot_{team}_c_{cycleTurn}_fightingDiff'])
                    teamScore.unexplainedTileDelta = int(data[f'ot_{team}_c_{cycleTurn}_unexplainedTileDelta'])

                if f'ot_{team}_c_{cycleTurn}_stats_moves_spent_capturing_fog_tiles' in data:
                    stats = CycleStatsData(team, teamPlayers)
                    stats.moves_spent_capturing_fog_tiles = int(data[f'ot_{team}_c_{cycleTurn}_stats_moves_spent_capturing_fog_tiles'])
                    stats.moves_spent_capturing_visible_tiles = int(data[f'ot_{team}_c_{cycleTurn}_stats_moves_spent_capturing_visible_tiles'])
                    stats.moves_spent_gathering_fog_tiles = int(data[f'ot_{team}_c_{cycleTurn}_stats_moves_spent_gathering_fog_tiles'])
                    stats.moves_spent_gathering_visible_tiles = int(data[f'ot_{team}_c_{cycleTurn}_stats_moves_spent_gathering_visible_tiles'])
                    stats.approximate_army_gathered_this_cycle = int(data[f'ot_{team}_c_{cycleTurn}_stats_approximate_army_gathered_this_cycle'])
                    stats.army_annihilated_visible = int(data[f'ot_{team}_c_{cycleTurn}_stats_army_annihilated_visible'])
                    stats.army_annihilated_fog = int(data[f'ot_{team}_c_{cycleTurn}_stats_army_annihilated_fog'])
                    stats.army_annihilated_total = int(data[f'ot_{team}_c_{cycleTurn}_stats_army_annihilated_total'])
                    stats.approximate_fog_army_available_total = int(data[f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_army_available_total'])
                    if f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_army_available_total_true' in data:
                        stats.approximate_fog_army_available_total_true = int(data[f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_army_available_total_true'])
                    else:
                        stats.approximate_fog_army_available_total_true = int(data[f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_army_available_total'])
                    stats.approximate_fog_city_army = int(data[f'ot_{team}_c_{cycleTurn}_stats_approximate_fog_city_army'])
                    self.team_cycle_stats_history[team][cycleTurn] = stats

        for team in self._team_indexes:
            stats = self.current_team_cycle_stats[team]
            if stats is None:
                stats = CycleStatsData(team, self.get_team_players(team))
                self.current_team_cycle_stats[team] = stats
            if f'ot_{team}_stats_moves_spent_capturing_fog_tiles' in data:
                stats.moves_spent_capturing_fog_tiles = int(data[f'ot_{team}_stats_moves_spent_capturing_fog_tiles'])
                stats.moves_spent_capturing_visible_tiles = int(data[f'ot_{team}_stats_moves_spent_capturing_visible_tiles'])
                stats.moves_spent_gathering_fog_tiles = int(data[f'ot_{team}_stats_moves_spent_gathering_fog_tiles'])
                stats.moves_spent_gathering_visible_tiles = int(data[f'ot_{team}_stats_moves_spent_gathering_visible_tiles'])
                stats.approximate_army_gathered_this_cycle = int(data[f'ot_{team}_stats_approximate_army_gathered_this_cycle'])
                stats.army_annihilated_visible = int(data[f'ot_{team}_stats_army_annihilated_visible'])
                stats.army_annihilated_fog = int(data[f'ot_{team}_stats_army_annihilated_fog'])
                stats.army_annihilated_total = int(data[f'ot_{team}_stats_army_annihilated_total'])
                stats.approximate_fog_army_available_total = int(data[f'ot_{team}_stats_approximate_fog_army_available_total'])
                if f'ot_{team}_stats_approximate_fog_army_available_total_true' in data:
                    stats.approximate_fog_army_available_total_true = int(data[f'ot_{team}_stats_approximate_fog_army_available_total_true'])
                else:
                    stats.approximate_fog_army_available_total_true = int(data[f'ot_{team}_stats_approximate_fog_army_available_total'])
                stats.approximate_fog_city_army = int(data[f'ot_{team}_stats_approximate_fog_city_army'])

        for player in self.map.players:
            if player.index == self.map.player_index or player.index in self.map.teammates:
                continue

            if f'ot_{PLAYER_CHAR_BY_INDEX[player.index]}_tcs' in data:
                fq = FogGatherQueue(player.index)
                self._gather_queues_new_by_player[player.index] = fq
                countsSplit = data[f'ot_{PLAYER_CHAR_BY_INDEX[player.index]}_tcs'].split('|')

                for sizeCountStr in countsSplit:
                    if 'x' in sizeCountStr:
                        countStr, sizeStr = sizeCountStr.strip().strip('s').split('x')
                        size = int(sizeStr)
                        num = int(countStr)

                        fq.set_amount_for_size(size, num)

        for team in self._team_indexes:
            self._update_cycle_stats_and_moves_no_checks(team, self.map.get_team_stats_by_team_id(team), self.get_last_cycle_end_turn(), skipTurn=True)

        self.skip_this_turn = True

    def calculate_cycle_stats(self, team: int, curTurnScores: TeamStats) -> CycleStatsData | None:
        lastCycleEndTurn = self.get_last_cycle_end_turn()
        if lastCycleEndTurn is None:
            return None

        currentCycleStats, lastCycleScores = self._update_cycle_stats_and_moves_no_checks(team, curTurnScores, lastCycleEndTurn)

        isCycleEnd = self.map.is_army_bonus_turn
        isCityBonus = self.map.is_city_bonus_turn
        if isCityBonus:
            self._include_city_bonus(currentCycleStats)

        if isCycleEnd:
            self.team_score_data_history[team][self.map.turn] = curTurnScores
            self.team_cycle_stats_history[team][self.map.turn] = currentCycleStats

            # reset certain things after recording the final cycle stuff

            currentCycleStats = self._start_next_cycle(currentCycleStats, lastCycleStats=currentCycleStats, currentTeamStats=curTurnScores, lastCycleTeamStats=lastCycleScores)
            self.current_team_cycle_stats[currentCycleStats.team] = currentCycleStats

        self._check_missing_fog_gather_tiles(currentCycleStats)

        self._validate_army_totals(curTurnScores, currentCycleStats)

        return currentCycleStats

    def _update_cycle_stats_and_moves_no_checks(self, team: int, curTurnScores: TeamStats, lastCycleEndTurn: int, skipTurn: bool = False):
        lastTurnScores = self.current_team_scores[team]
        currentCycleStats = self.current_team_cycle_stats[team]
        if currentCycleStats is None:
            currentCycleStats = self.initialize_cycle_stats(team)

        lastCycleScores = self.team_score_data_history[team].get(lastCycleEndTurn, None)
        # lastCycleStats = self.team_cycle_stats_history[team].get(lastCycleEndTurn, None)

        if not skipTurn:
            self._handle_emergences(currentCycleStats)
            self._handle_moves_into_fog(currentCycleStats)
            self._update_team_cycle_stats_based_on_turn_deltas(currentCycleStats, currentTeamStats=curTurnScores, lastTurnTeamStats=lastTurnScores)

            self._handle_reveals(currentCycleStats)
            self._handle_vision_losses(currentCycleStats)
        self._update_team_cycle_stats_relative_to_last_cycle(currentCycleStats, currentTeamStats=curTurnScores, lastCycleScores=lastCycleScores)

        return currentCycleStats, lastCycleScores

    def _update_team_cycle_stats_based_on_turn_deltas(self, currentCycleStats: CycleStatsData, currentTeamStats: TeamStats, lastTurnTeamStats: TeamStats):
        unexplainedTileDelta = 0

        for playerIdx in currentCycleStats.players:
            player = self.map.players[playerIdx]
            if player.dead:
                continue

            unexplainedTileDelta += player.unexplainedTileDelta

            if player.last_move is None:
                self._check_missing_move(player, currentCycleStats, currentTeamStats=currentTeamStats)
            else:
                self._check_visible_move(player, currentCycleStats)

    def initialize_cycle_stats(self, team: int) -> CycleStatsData:
        players = self.get_team_players(team)
        stats = CycleStatsData(team, players)
        return stats

    def get_team_players(self, team: int) -> typing.List[int]:
        if team == -1:
            return [-1]
        return self._players_lookup_by_team[team]

    def get_team_players_by_player(self, player: int) -> typing.List[int]:
        if player == -1:
            return [-1]
        return self._players_lookup_by_team[self._team_lookup_by_player[player]]

    def did_player_make_fog_capture_move(self, player: int) -> bool:
        return self.last_player_move_type[player] == PlayerMoveCategory.FogCapture

    def did_player_make_fog_gather_move(self, player: int) -> bool:
        return self.last_player_move_type[player] == PlayerMoveCategory.FogGather

    def _check_missing_move(self, player: Player, currentCycleStats: CycleStatsData, currentTeamStats: TeamStats):
        # if player.unexplainedTileDelta > 5:
        #     # they captured someone, ignore...?
        #     return
        #
        # elif player.unexplainedTileDelta > 0:
        playerAnnihilated = player.expectedScoreDelta - player.actualScoreDelta

        hasPerfectPlayerInfo = self.map.remainingPlayers == 2 or self.map.is_2v2
        isPotentialMultiPartFogCap = player.tileCount > 0 and (playerAnnihilated > player.standingArmy // player.tileCount or (playerAnnihilated > 1 and hasPerfectPlayerInfo))

        if player.unexplainedTileDelta > 0 and currentTeamStats.unexplainedTileDelta >= 0:
            teamAnnihilatedFog = self._get_team_annihilated_fog_internal(currentTeamStats, player)

            if teamAnnihilatedFog > 0:
                tookCity = player.lastCityCount < player.cityCount
                reason = 'attacked another player'
                if tookCity:
                    reason = 'captured city'

                logbook.info(f'Assuming p{player.index} {reason} under fog, annihilated {playerAnnihilated}.')
                # player is fighting a player in the fog and capped their tile (or attacked neutral non-zero tiles)
                self._assume_fog_player_capture_move(player, currentCycleStats, teamAnnihilatedFog)
            elif teamAnnihilatedFog < 0:
                logbook.error(f'This should be impossible unless we mis-counted cities... p{player.index} captured ally tile under fog (or ffa player capture?), annihilated {playerAnnihilated}.')
                # they must have captured someone or taken an allied tile
                self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=True)
            else:
                logbook.info(f'Assuming p{player.index} captured neutral tile in fog, annihilated {playerAnnihilated}.')
                # must be neutral capture
                self._assume_fog_empty_tile_capture_move(player, currentCycleStats)
            #
            # if teamAnnihilatedFog != 0 and self.map.is_player_on_team_with(player.fighting_with_player, player.index):
            #     # then captured a neutral tile, otherwise captured the delta worth of other player fight delta
        elif player.unexplainedTileDelta < 0:
            if currentTeamStats.unexplainedTileDelta < 0:
                logbook.info(f'Assuming p{player.index} was under attack under the fog, annihilated {playerAnnihilated}.')
                self._assume_fog_under_attack_move(player, currentCycleStats, tileCapturedBySomeoneElse=True, annihilated=playerAnnihilated)
            else:
                # ally took one of their tiles, and they gathered, so this is also just a fog gather move
                logbook.info(f'Assuming p{player.index} had a tile captured by their ally, fog gather move.')
                self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)
        elif isPotentialMultiPartFogCap:
            # player capping neutral city, or something? or being attacked for non-lethal tile damage? Probably no-op here, but lets assume gather move for now.
            logbook.info(f'Assuming p{player.index} half-capture despite no tile change because army annihilation of {playerAnnihilated}.')
            self._assume_fog_player_capture_move(player, currentCycleStats, annihilatedFogArmy=playerAnnihilated, noCapture=True)
        elif playerAnnihilated > 0:
            # player capping neutral city, or something? or being attacked for non-lethal tile damage? Probably no-op here, but lets assume gather move for now.
            logbook.info(f'Assuming p{player.index} gathermove because no tile change DESPITE army annihilation of {playerAnnihilated}.')
            self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)
        else:
            logbook.info(f'Assuming p{player.index} gathermove based on no detected changes. playerAnnihilated {playerAnnihilated}')
            self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)

    def _check_visible_move(self, player: Player, currentCycleStats: CycleStatsData):
        source: Tile
        dest: Tile
        source, dest, movedHalf = player.last_move
        if self.map.is_player_on_team_with(player.index, dest.delta.oldOwner):
            if dest.visible:
                if dest.delta.oldArmy > 1 or not dest.delta.gainedSight:
                    currentCycleStats.moves_spent_gathering_visible_tiles += 1
                    self.last_player_move_type[player.index] = PlayerMoveCategory.VisibleGather
                else:
                    self.last_player_move_type[player.index] = PlayerMoveCategory.Wasted
            else:
                currentCycleStats.moves_spent_gathering_fog_tiles += 1
                self.last_player_move_type[player.index] = PlayerMoveCategory.FogGather
        else:
            currentCycleStats.moves_spent_capturing_visible_tiles += 1
            currentCycleStats.army_annihilated_visible -= source.delta.armyDelta
            if dest.player == player.index:
                currentCycleStats.army_annihilated_visible -= dest.army - dest.delta.expectedDelta

            self.last_player_move_type[player.index] = PlayerMoveCategory.VisibleCapture

    def _assume_fog_gather_move(self, player: Player, currentCycleStats: CycleStatsData, gatheringAllyTile: bool):
        playerToGatherFromQueue = player.index
        if gatheringAllyTile:
            for pIdx in currentCycleStats.players:
                if pIdx == player.index:
                    continue
                playerToGatherFromQueue = pIdx

        gatherQueueSource = self.get_player_gather_queue(playerToGatherFromQueue)
        gatherVal = gatherQueueSource.pop_next_highest(leaveOne=False)
        if gatherVal:
            gatherQueueDest = self.get_player_gather_queue(player.index)
            gatherQueueDest.append(1)

            currentCycleStats.approximate_army_gathered_this_cycle += gatherVal - 1
            currentCycleStats.approximate_fog_army_available_total += gatherVal - 1
            currentCycleStats.approximate_fog_army_available_total_true += gatherVal - 1
            logbook.info(f'increasing p{player.index}s gather value by {gatherVal}')
        else:
            logbook.info(f'No gather value to dequeue for p{player.index} ')
            # then assume launch from city!?
            # if currentCycleStats.approximate_fog_city_army > 0:
            #     currentCycleStats.approximate_fog_army_available_total += self.pull_one_fog_city_army(player.index)
            #     currentCycleStats.approximate_fog_army_available_total_true += self.pull_one_fog_city_army(player.index)

        currentCycleStats.moves_spent_gathering_fog_tiles += 1
        self.last_player_move_type[player.index] = PlayerMoveCategory.FogGather

    def _assume_fog_empty_tile_capture_move(self, player: Player, currentCycleStats: CycleStatsData):
        """Apply a zero-value neutral tile capture (so, no army was annihilated). Prefers using 2's to capture empty tiles before using gathered army."""
        gatherQueue = self.get_player_gather_queue(player.index)

        if not self._try_remove_queued_gather_for_amount(player.index, 2, leaveOne=True):
            currentCycleStats.approximate_army_gathered_this_cycle -= 1
            currentCycleStats.approximate_fog_army_available_total -= 1
            currentCycleStats.approximate_fog_army_available_total_true -= 1

        self._check_available_fog_army(currentCycleStats, forceFullArmyUsageFirst=True)

        currentCycleStats.moves_spent_capturing_fog_tiles += 1
        currentCycleStats.tiles_gained += 1
        gatherQueue.append(1)

        self.last_player_move_type[player.index] = PlayerMoveCategory.FogCapture

    def _assume_fog_player_capture_move(self, player: Player, currentCycleStats: CycleStatsData, annihilatedFogArmy: int, noCapture: bool = False):
        currentCycleStats.army_annihilated_fog += annihilatedFogArmy
        currentCycleStats.approximate_army_gathered_this_cycle -= annihilatedFogArmy
        currentCycleStats.approximate_fog_army_available_total -= annihilatedFogArmy
        currentCycleStats.approximate_fog_army_available_total_true -= annihilatedFogArmy
        gatherQueue = self.get_player_gather_queue(player.index)

        # if the annihilated army overdraws us, but they have a gatherable tile greater than the overdrawn amount, use that tile to perform the capture instead of using our gathered fog army.
        if currentCycleStats.approximate_fog_army_available_total < 0 and gatherQueue.peek_next_highest() > annihilatedFogArmy + 2:  # +2 because to capture they should have 1 tile left on source and 1 tile on dest. Usually they wont be colliding non-capture in the fog.
            self._remove_queued_gather_closest_to_amount(player.index, annihilatedFogArmy + 2, leaveOne=True)
            currentCycleStats.approximate_army_gathered_this_cycle += annihilatedFogArmy
            currentCycleStats.approximate_fog_army_available_total += annihilatedFogArmy
            currentCycleStats.approximate_fog_army_available_total_true += annihilatedFogArmy

        self._check_available_fog_army(currentCycleStats, forceFullArmyUsageFirst=True)

        currentCycleStats.moves_spent_capturing_fog_tiles += 1

        if not noCapture:
            currentCycleStats.approximate_army_gathered_this_cycle -= 1
            currentCycleStats.approximate_fog_army_available_total -= 1
            currentCycleStats.approximate_fog_army_available_total_true -= 1
            currentCycleStats.tiles_gained += 1
            gatherQueue.append(1)

        self.last_player_move_type[player.index] = PlayerMoveCategory.FogCapture

    def _assume_fog_under_attack_move(self, player: Player, currentCycleStats: CycleStatsData, tileCapturedBySomeoneElse: bool, annihilated: int):
        if tileCapturedBySomeoneElse:
            currentCycleStats.tiles_gained -= 1
        else:
            self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)
        # if player.fighting_with_player != -1:

        if annihilated <= self.assumed_player_average_tile_values[player.index] * 1.5:
            # then we assume they didnt use gathered army to block the attack and weren't just having land taken.
            removed = self._remove_queued_gather_closest_to_amount(player.index, annihilated, leaveOne=False)
            annihilated -= removed

        currentCycleStats.approximate_fog_army_available_total -= annihilated
        currentCycleStats.approximate_fog_army_available_total_true -= annihilated
        currentCycleStats.approximate_army_gathered_this_cycle -= annihilated

    def recalculate_average_tile_values(self):
        for team in self._team_indexes:
            curCycleStats = self.current_team_cycle_stats[team]
            curTeamStats = self.current_team_scores[team]
            lastCycleStats = self.get_last_cycle_stats_by_team(team)

            if curCycleStats is None:
                continue

            teamHasGatheredAllTiles = curCycleStats.approximate_army_gathered_this_cycle >= curTeamStats.standingArmy - curCycleStats.approximate_fog_city_army

            teamAverageUngatheredTileVal = self._calculate_tile_average_value(curCycleStats, curTeamStats, lastCycleStats)

            for playerIndex in self._players_lookup_by_team[team]:
                player = self.map.players[playerIndex]
                if player.dead:
                    self.assumed_player_average_tile_values[player.index] = 0.0
                    continue

                if teamHasGatheredAllTiles:
                    logbook.info(f"PLAYER GATHERED ALL TILES? CALCED {teamAverageUngatheredTileVal} VS OUR EXPECTED 1.0")
                    teamAverageUngatheredTileVal = 1.0

                self.assumed_player_average_tile_values[player.index] = teamAverageUngatheredTileVal

    def _calculate_tile_average_value(self, curCycleStats: CycleStatsData, curTeamStats: TeamStats, lastCycleStats: CycleStatsData | None) -> float:
        """
        What is probably the average value of the tiles this player has besides cities and stuff.

        @param curCycleStats:
        @param curTeamStats:
        @return:
        """

        fogTileCount, fogArmyAmount, fogCityCount, playerCount = self.calculate_team_fog_tile_data(curCycleStats.team)

        # if (self.map.turn - 1) % 50 == 0:
        #     # 2s count = last cycle gathered turns + lastCycle fog captures, everything else we assume keeps growing
        #     num2s = 0
        #     if lastCycleStats is not None:
        #         num2s += lastCycleStats.moves_spent_gathering_fog_tiles
        #         num2s += lastCycleStats.moves_spent_capturing_fog_tiles
        #     curCycleStats.approximate_number_of_2s = num2s

        relevantFogArmy = fogArmyAmount - curCycleStats.approximate_army_gathered_this_cycle - curCycleStats.approximate_fog_city_army

        ungatheredTileCount = fogTileCount - curCycleStats.moves_spent_gathering_fog_tiles - fogCityCount
        #
        # tileDistribution = [2] * min(ungatheredTileCount, curCycleStats.approximate_number_of_2s)
        #
        # movesExpectedToGather = 25 * playerCount

        average = 0.0
        if ungatheredTileCount > 0:
            average = relevantFogArmy / ungatheredTileCount

        return average

    def get_last_cycle_stats_by_team(self, team: int, cyclesToGoBack: int = 0) -> CycleStatsData | None:
        lastCycleTurn = self.get_last_cycle_end_turn(cyclesToGoBack=cyclesToGoBack)
        return self.team_cycle_stats_history[team].get(lastCycleTurn, None)

    def get_last_cycle_stats_by_player(self, player: int, cyclesToGoBack: int = 0) -> CycleStatsData | None:
        return self.get_last_cycle_stats_by_team(self._team_lookup_by_player[player], cyclesToGoBack=cyclesToGoBack)

    def get_last_cycle_score_by_team(self, team: int, cyclesToGoBack: int = 0) -> TeamStats | None:
        lastCycleTurn = self.get_last_cycle_end_turn(cyclesToGoBack=cyclesToGoBack)
        return self.team_score_data_history[team].get(lastCycleTurn, None)

    def get_last_cycle_score_by_player(self, player: int, cyclesToGoBack: int = 0) -> TeamStats | None:
        return self.get_last_cycle_score_by_team(self._team_lookup_by_player[player], cyclesToGoBack=cyclesToGoBack)

    def get_player_gather_queue(self, player: int) -> FogGatherQueue:
        if player == -1:
            raise AssertionError(f'Player p{player} is not a valid player to retrieve a gather queue for')
        return self._gather_queues_new_by_player[player]

    def _update_team_cycle_stats_relative_to_last_cycle(
        self,
        currentCycleStats,
        currentTeamStats,
        lastCycleScores
    ):
        # in theory this should be kept up to date
        calculatedTilesGained = currentTeamStats.tileCount - lastCycleScores.tileCount
        if calculatedTilesGained != currentCycleStats.tiles_gained:
            logbook.info(f'team[{currentCycleStats.team}]: calculatedTilesGained {calculatedTilesGained} != currentCycleStats.tiles_gained {currentCycleStats.tiles_gained}, updating...')
            currentCycleStats.tiles_gained = calculatedTilesGained

        currentCycleStats.score_gained = currentTeamStats.score - lastCycleScores.score
        currentCycleStats.cities_gained = currentTeamStats.cityCount - lastCycleScores.cityCount

        # currentCycleStats.moves_spent_capturing_fog_tiles = currentCycleStats.moves_spent_capturing_fog_tiles
        # currentCycleStats.moves_spent_capturing_visible_tiles = currentCycleStats.moves_spent_capturing_visible_tiles
        # currentCycleStats.moves_spent_gathering_fog_tiles = currentCycleStats.moves_spent_gathering_fog_tiles
        # currentCycleStats.moves_spent_gathering_visible_tiles = currentCycleStats.moves_spent_gathering_visible_tiles

        # currentCycleStats.approximate_army_gathered_this_cycle = currentCycleStats.approximate_army_gathered_this_cycle
        # currentCycleStats.army_annihilated_visible = currentCycleStats.army_annihilated_visible
        # currentCycleStats.army_annihilated_fog = currentCycleStats.army_annihilated_fog
        # currentCycleStats.army_annihilated_total = currentCycleStats.army_annihilated_total
        # currentCycleStats.approximate_fog_army_available_total = currentCycleStats.approximate_fog_army_available_total
        # currentCycleStats.approximate_fog_army_available_total_true = currentCycleStats.approximate_fog_army_available_total_true
        # currentCycleStats.approximate_fog_city_army = currentCycleStats.approximate_fog_city_army

    def _start_next_cycle(
            self,
            currentCycleStats: CycleStatsData,
            lastCycleStats: CycleStatsData,
            currentTeamStats: TeamStats,
            lastCycleTeamStats: TeamStats
    ):
        nextStats = CycleStatsData(currentCycleStats.team, currentCycleStats.players)

        nextStats.approximate_fog_army_available_total = currentCycleStats.approximate_fog_army_available_total
        nextStats.approximate_fog_army_available_total_true = currentCycleStats.approximate_fog_army_available_total_true
        nextStats.approximate_fog_city_army = currentCycleStats.approximate_fog_city_army
        fogTileCount, fogArmyAmount, fogCityCount, playerCountAliveOnTeam = self.calculate_team_fog_tile_data(currentCycleStats.team)
        # fog cities also get army bonus, and this is cycle bonus turn.
        nextStats.approximate_fog_city_army += fogCityCount

        for player in currentCycleStats.players:
            gatherQueue = self.get_player_gather_queue(player)
            gatherQueue.increment_army_bonus()

        return nextStats

    def _handle_emergences(self, currentCycleStats: CycleStatsData):
        handled = set()
        for tile, emergingPlayer, emergence in self._emergences:
            if tile in handled:
                continue

            logbook.info(f'oppTracker _handle_emergences: {tile} for p{emergingPlayer}, amount {emergence}')

            handled.add(tile)
            if tile.delta.gainedSight:
                continue  # handled by revealed handler
            if emergence < 0:
                emergence = abs(emergence) - 1

            if emergingPlayer in currentCycleStats.players:
                self._execute_emergence(currentCycleStats, tile, emergence, emergingPlayer)

    def _handle_moves_into_fog(self, currentCycleStats: CycleStatsData):
        used = set()
        for army in self._moves_into_fog:
            if army.player not in currentCycleStats.players:
                continue

            if army.name in used:
                continue

            if army.last_seen_turn < self.map.turn - 1:
                continue

            stats = self.get_current_cycle_stats_by_player(army.player)
            stats.approximate_fog_army_available_total += army.value
            stats.approximate_fog_army_available_total_true += army.value
            used.add(army.name)

    def _handle_reveals(self, currentCycleStats: CycleStatsData):
        for tile in self._revealed:
            if tile.player not in currentCycleStats.players:
                continue

            fogTileCount, fogArmyAmount, fogCityCount = self.calculate_player_fog_tile_data(tile.player)
            gathQueue = self.get_player_gather_queue(tile.player)
            armyThresh = max(1, gathQueue.peek_next_highest())

            armyToUse = max(abs(tile.delta.unexplainedDelta), tile.army)

            if tile.isCity or tile.isGeneral:
                logbook.info(f'V+: {repr(tile)} - team[{currentCycleStats.team}] city/gen revealed, reducing fog city amt by that.')
                currentCycleStats.approximate_fog_city_army -= armyToUse
            elif gathQueue.length > fogTileCount - fogCityCount:
                logbook.info(f'V+: {repr(tile)} - removing p{tile.player} queued gather closest to army {armyToUse}, gathQueue.length {gathQueue.length} > fogTileCount {fogTileCount} - fogCityCount {fogCityCount}')
                self._remove_queued_gather_closest_to_amount(tile.player, armyToUse, leaveOne=False)

            if armyToUse > armyThresh:
                logbook.info(f'V+: {repr(tile)} - team[{currentCycleStats.team}] large tile revealed {armyToUse} > {armyThresh}, reducing fog army by that.')
                self._execute_emergence(currentCycleStats, tile, armyToUse - 1)

    def _handle_vision_losses(self, currentCycleStats: CycleStatsData):
        """
        The tiles we lost vision of in the fog should have already had any increments applied to them by the map class,
         so we should put it in the gather queue AFTER we do any gather-queue-increment stuff.

        @param currentCycleStats:
        @return:
        """
        for tile in self._vision_losses:
            if tile.player not in currentCycleStats.players:
                continue

            playerGathQueue = self.get_player_gather_queue(tile.player)

            gathCutoff = 2
            if playerGathQueue.gatherable_length > 0:
                gathCutoff = playerGathQueue.peek_next_highest() * 1.5

            if tile.isCity or tile.isGeneral:
                logbook.info(f'V-: {repr(tile)} - p{tile.player} city/gen vision lost, adding that amount to fog city army')
                # TODO do we actually want this? Feels like we should only track this for unknown cities, since we're
                #  already incrementing THESE cities directly as we know where they are, and armyTracker fog emergence
                #  already reduces them...?
                currentCycleStats.approximate_fog_city_army += tile.army - 1
            elif tile.army > gathCutoff:
                # then immediately count this as gathered army and put a 1 in the queue, instead.
                # TODO track BFS movement through the fog of this amount instead of immediately making it available as
                #  a flank threat instead, since we know where it last was...?
                # TODO Why do this at all? Make them spend one turn gathering these large tiles to include them in army, why not...?
                logbook.info(f'V-: {repr(tile)} - p{tile.player} large tile {tile.army} > gathCutoff {gathCutoff:.1f}, so counting towards fog army. Counting tile as gatherable 1')
                currentCycleStats.approximate_fog_army_available_total += tile.army - 1
                currentCycleStats.approximate_fog_army_available_total_true += tile.army - 1

                # They DIDNT gather this this cycle (or if they did it was already recorded) so DONT do the below.
                # currentCycleStats.approximate_army_gathered_this_cycle += tile.army - 1

                playerGathQueue.append(1)
            else:
                logbook.info(f'V-: {repr(tile)} - p{tile.player} vision lost, adding {tile.army} to the gather queue.')
                self.insert_amount_into_player_gather_queue(tile.player, tile.army)

    def _remove_queued_gather_closest_to_amount(self, player: int, tileAmount: int, leaveOne: bool) -> int:
        """Returns the amount that was actually removed."""
        q = self.get_player_gather_queue(player)

        return q.remove_queued_gather_closest_to_amount(tileAmount, leaveOne=leaveOne)

    def _try_remove_queued_gather_for_amount(self, player: int, tileAmount: int, leaveOne: bool) -> bool:
        q = self.get_player_gather_queue(player)

        return q.try_remove_queued_gather_for_exact_amount(tileAmount, leaveOne=leaveOne)

    def insert_amount_into_player_gather_queue(self, player: int, tileAmount: int):
        q = self.get_player_gather_queue(player)

        q.append(tileAmount)

    def calculate_team_fog_tile_data(self, team: int) -> typing.Tuple[int, int, int, int]:
        """
        Returns fogTileCount, fogArmyAmount, fogCityCount, playerCountAliveOnTeam
        @param team:
        @return:
        """
        fogTileCount = 0
        fogArmyAmount = 0
        playerCountAliveOnTeam = 0
        fogCityCount = 0
        for player in self.map.players:
            if player.dead:
                continue
            if not self._team_lookup_by_player[player.index] == team:
                continue

            playerCountAliveOnTeam += 1
            playerFogTileCount, playerFogArmyAmount, playerFogCityCount = self.calculate_player_fog_tile_data(player.index)

            fogTileCount += playerFogTileCount
            fogArmyAmount += playerFogArmyAmount
            fogCityCount += playerFogCityCount

        return fogTileCount, fogArmyAmount, fogCityCount, playerCountAliveOnTeam

    def calculate_player_fog_tile_data(self, playerIndex: int) -> typing.Tuple[int, int, int]:
        """
        Returns fogTileCount, fogArmyAmount, fogCityCount
        @param playerIndex:
        @return:
        """
        player = self.map.players[playerIndex]
        playerFogTileCount = player.tileCount
        playerFogArmyAmount = player.score
        playerFogCityCount = player.cityCount
        for tile in player.tiles:
            if tile.visible:
                playerFogTileCount -= 1
                playerFogArmyAmount -= tile.army
                if tile.isGeneral or tile.isCity:
                    playerFogCityCount -= 1

        return playerFogTileCount, playerFogArmyAmount, playerFogCityCount

    def _include_city_bonus(self, currentCycleStats: CycleStatsData):
        fogTileCount, fogArmyAmount, fogCityCount, playerCountAliveOnTeam = self.calculate_team_fog_tile_data(currentCycleStats.team)

        currentCycleStats.approximate_fog_city_army += fogCityCount

    def _check_available_fog_army(self, currentCycleStats: CycleStatsData, forceFullArmyUsageFirst: bool = False):
        if currentCycleStats.approximate_fog_army_available_total >= 0:
            return

        pulled = self.pull_team_fog_army_from_fog_cities(
            currentCycleStats.team,
            amount=0 - currentCycleStats.approximate_fog_army_available_total,
            pullFullCityWorth=not forceFullArmyUsageFirst
        )

        currentCycleStats.approximate_fog_army_available_total += pulled
        currentCycleStats.approximate_fog_army_available_total_true += pulled

    def pull_team_fog_army_from_fog_cities(
            self,
            team: int,
            amount: int,
            pullFullCityWorth: bool = False
    ) -> int:
        """
        Removes and returns some amount of fog city army.

        @param team:
        @param amount:
        @param pullFullCityWorth: If true, will not gather partial cities. So may return more than asked for.
        @return: If pullFullCityWorth will return 'amount' if enough is available, otherwise will return however much is available and set fog cities to zero.
        """

        currentCycleStats = self.current_team_cycle_stats[team]

        return self._internal_pull_team_fog_army_from_fog_cities(currentCycleStats, amount, pullFullCityWorth)

    def pull_player_fog_army_from_fog_cities(
            self,
            player: int,
            amount: int,
            pullFullCityWorth: bool = False
    ) -> int:
        """
        Removes and returns some amount of fog city army.

        @param player:
        @param amount:
        @param pullFullCityWorth: If true, will not gather partial cities. So may return more than asked for.
        @return: If pullFullCityWorth will return 'amount' if enough is available, otherwise will return however much is available and set fog cities to zero.
        """

        return self.pull_team_fog_army_from_fog_cities(self._team_indexes[player], amount, pullFullCityWorth)

    def _internal_pull_team_fog_army_from_fog_cities(
            self,
            currentCycleStats: CycleStatsData,
            amount: int,
            pullFullCityWorth: bool = False
    ) -> int:
        """
        Removes and returns some amount of fog city army.
        TODO eventually this should 'gather' individual fog cities instead of just pulling from the ratiod pool like it does now.

        @param currentCycleStats:
        @param amount:
        @param pullFullCityWorth: If true, will not gather partial cities. So may return more than asked for.
        @return: If pullFullCityWorth will return 'amount' if enough is available, otherwise will return however much is available and set fog cities to zero.
        """

        fogCityOriginalAmount = currentCycleStats.approximate_fog_city_army

        if fogCityOriginalAmount <= 0:
            return 0

        if fogCityOriginalAmount <= amount:
            currentCycleStats.approximate_fog_city_army = 0
            return fogCityOriginalAmount

        if not pullFullCityWorth:
            currentCycleStats.approximate_fog_city_army -= amount
            return amount

        # otherwise, we need to pull a full fog city worth of army.
        fogTileCount, fogArmyAmount, fogCityCount, playerCountAliveOnTeam = self.calculate_team_fog_tile_data(currentCycleStats.team)

        if fogCityCount <= 0:
            return 0

        armyPerFogCity = fogCityOriginalAmount // fogCityCount

        for i in range(fogCityCount):
            if currentCycleStats.approximate_fog_army_available_total >= 0:
                break

            logbook.info(
                f'FogCheck: team[{currentCycleStats.team}] approximate_fog_army_available_total {currentCycleStats.approximate_fog_army_available_total} <= 0 (true was {currentCycleStats.approximate_fog_army_available_total_true}), pulling from fog cities which each are estimated at armyPerFogCity {armyPerFogCity}')

            currentCycleStats.approximate_fog_army_available_total += armyPerFogCity
            currentCycleStats.approximate_fog_army_available_total_true += armyPerFogCity
            currentCycleStats.approximate_fog_city_army -= armyPerFogCity

    def get_all_player_fog_tile_count_dict(self) -> typing.Dict[int, typing.Dict[int, int]]:
        gatherValueCountsByPlayer = {}
        for player in self.map.players:
            gatherValueCountsByPlayer[player.index] = self.get_player_gather_queue(player.index).get_amount_dict()

        return gatherValueCountsByPlayer

    def get_player_fog_tile_count_dict(self, playerIndex: int) -> typing.Dict[int, int]:
        player = self.map.players[playerIndex]
        return self.get_player_gather_queue(player.index).get_amount_dict()

    def _check_missing_fog_gather_tiles(self, currentCycleStats: CycleStatsData):
        for playerIdx in currentCycleStats.players:
            playerFogTileCount, playerFogArmyAmount, playerFogCityCount = self.calculate_player_fog_tile_data(playerIdx)
            # we dont include their cities in the gatherable tile list
            playerFogGathTileCount = playerFogTileCount - playerFogCityCount
            queue = self.get_player_gather_queue(playerIdx)
            while queue.length < playerFogGathTileCount:
                logbook.error(f'CheckMissingFogGath: p{playerIdx} team[{currentCycleStats.team}] is missing fog tiles (q {queue.length} vs actual {playerFogGathTileCount})...? Adding a 1')
                queue.append(1)

    def get_current_cycle_stats_by_player(self, player: int) -> CycleStatsData:
        return self.current_team_cycle_stats[self._team_lookup_by_player[player]]

    def get_current_team_scores_by_player(self, player: int) -> TeamStats:
        return self.current_team_scores[self._team_lookup_by_player[player]]

    def _execute_emergence(self, currentCycleStats: CycleStatsData, tile: Tile, emergence: int, player: int = -2):
        if player == -2:
            player = tile.player

        teamScores = self.current_team_scores[currentCycleStats.team]
        teamTotalFogEmergenceEst = currentCycleStats.approximate_fog_army_available_total + currentCycleStats.approximate_fog_city_army - max(0, 3 * (teamScores.cityCount - 1)) - max(0, 6 * (teamScores.cityCount - 2))

        # .90 seemed high
        thresh = (teamTotalFogEmergenceEst - 1) * 0.87

        fullFogReset = False
        if emergence > thresh:
            logbook.info(
                f'E+: fullFogReset - emergence {emergence} > thresh {thresh:.1f} (based on teamTotalFogEmergenceEst {teamTotalFogEmergenceEst})')
            if emergence > teamTotalFogEmergenceEst:
                msg = f'UNDEREST BY {emergence - teamTotalFogEmergenceEst}! E+: fullFogReset - emergence {emergence} > thresh {thresh:.1f} (based on teamTotalFogEmergenceEst {teamTotalFogEmergenceEst})'
                logbook.error(msg)
                if self.view_info is not None:
                    self.view_info.add_info_line(msg)
                    self.view_info.add_targeted_tile(tile, TargetStyle.ORANGE)
            fullFogReset = True
            if emergence > teamTotalFogEmergenceEst - 4 and not (tile.delta.gainedSight and tile.army < emergence):
                maxDist = max(1, teamTotalFogEmergenceEst - emergence + 1) * 2
                self.view_info.add_info_line(f'BC emgnce {emergence} VS teamTotalFogEmergenceEst {teamTotalFogEmergenceEst}, CONF WITHIN {maxDist} {tile}')
                self.send_general_distance_notification(maxDist, tile, generalConfidence=teamScores.cityCount == 1)

        logbook.info(
            f'E+: {repr(tile)} - p{player} team[{currentCycleStats.team}] emergence {emergence} reducing approximate_fog_army_available_total')

        currentCycleStats.approximate_fog_army_available_total -= emergence
        currentCycleStats.approximate_fog_army_available_total_true -= emergence

        while currentCycleStats.approximate_fog_army_available_total < 0 and currentCycleStats.approximate_fog_city_army > 1:
            logbook.info(
                f'  E+: {repr(tile)} - p{player} team[{currentCycleStats.team}] emergence {emergence} brought approximate_fog_army_available_total {currentCycleStats.approximate_fog_army_available_total} below 0, using city values')
            currentCycleStats.approximate_fog_army_available_total += currentCycleStats.approximate_fog_city_army // 2
            currentCycleStats.approximate_fog_army_available_total_true += currentCycleStats.approximate_fog_city_army // 2
            currentCycleStats.approximate_fog_city_army -= currentCycleStats.approximate_fog_city_army // 2

        if fullFogReset:
            if currentCycleStats.approximate_fog_army_available_total + currentCycleStats.approximate_fog_city_army - 6 * teamScores.cityCount > teamTotalFogEmergenceEst * 0.1:
                currentCycleStats.approximate_fog_army_available_total = 0
                # TODO better estimation of city distances to gather path
                currentCycleStats.approximate_fog_city_army = 3 * teamScores.cityCount + max(0, (10 * teamScores.cityCount - 2))
                # TODO figure out how many incorrect assumption gathered tiles we assumed and put them back in the queue...?

        if currentCycleStats.approximate_fog_army_available_total < 0:
            self.view_info.add_info_line(f'team{currentCycleStats.team} approximate_fog_army_available_total NEGATIVE?? {currentCycleStats.approximate_fog_army_available_total} setting 0')
            currentCycleStats.approximate_fog_army_available_total = 0
        if currentCycleStats.approximate_fog_army_available_total_true < 0:
            self.view_info.add_info_line(f'team{currentCycleStats.team} approximate_fog_army_available_total_true NEGATIVE?? {currentCycleStats.approximate_fog_army_available_total_true} setting 0')
            currentCycleStats.approximate_fog_army_available_total_true = 0
        if currentCycleStats.approximate_fog_city_army < 0:
            self.view_info.add_info_line(f'team{currentCycleStats.team} approximate_fog_city_army NEGATIVE?? {currentCycleStats.approximate_fog_city_army} setting 0')
            currentCycleStats.approximate_fog_city_army = teamScores.cityCount

    def check_gather_move_differential(self, player: int, otherPlayer: int) -> int:
        """Positive means we spent more turns gathering, negative means they did."""
        playerStats = self.get_current_cycle_stats_by_player(player)
        otherPlayerStats = self.get_current_cycle_stats_by_player(otherPlayer)
        if playerStats is None or otherPlayerStats is None:
            return 0

        playerTurnsSpentGathering = playerStats.moves_spent_gathering_fog_tiles + playerStats.moves_spent_gathering_visible_tiles
        otherPlayerTurnsSpentGathering = otherPlayerStats.moves_spent_gathering_fog_tiles + otherPlayerStats.moves_spent_gathering_visible_tiles

        return playerTurnsSpentGathering - otherPlayerTurnsSpentGathering

    def get_approximate_greedy_turns_available(self, againstPlayer: int, ourArmyNonIncrement: int, cityLimit: int = 3, opponentArmyOffset: int = 0) -> int:
        stats = self.get_current_cycle_stats_by_player(againstPlayer)
        ourScores = self.get_current_team_scores_by_player(self.map.player_index)

        ourCities = ourScores.cityCount

        if stats is None:
            return 20

        armyRisk = stats.approximate_fog_army_available_total + opponentArmyOffset

        cityTotal = self.get_next_fog_city_amounts(againstPlayer, cityLimit=cityLimit)

        armyRisk += cityTotal

        gatherOffset = 0

        turn = self.map.turn
        remainingCycleTime = 50 - (self.map.turn % 50)
        enScores = self.get_current_team_scores_by_player(againstPlayer)
        queueLists = [self._gather_queues_new_by_player[p].as_tile_list() for p in stats.players]

        logEntries = [f'Running get_approximate_greedy_turns_available againstPlayer {againstPlayer}, ourArmyNonIncrement {ourArmyNonIncrement}, cityLimit {cityLimit}, opponentArmyOffset {opponentArmyOffset}. Opponent starting army risk: {armyRisk}, initial city total {cityTotal}']
        i = 0
        while turn < self.map.turn + 100:
            if turn & 1 == 0:
                armyRisk += min(cityLimit, enScores.cityCount)
                ourArmyNonIncrement += ourCities

            if remainingCycleTime == 0:
                armyRisk += 4
                armyRisk += cityTotal
                gatherOffset += 1
                remainingCycleTime = 50

            for q in queueLists:
                if i < len(q):
                    armyRisk += q[i] - 1 + gatherOffset
                else:
                    armyRisk += gatherOffset

            # logEntries.append(f't{turn}, usArmy {ourArmyNonIncrement}, theirArmy {armyRisk}')

            if armyRisk > ourArmyNonIncrement:
                logEntries.append(f'BROKE EVEN at t{turn}, usArmy {ourArmyNonIncrement}, theirArmy {armyRisk}. Returning.')
                break

            i += 1
            turn += 1

        logbook.info('\n'.join(logEntries))
        return i

    def get_approximate_fog_army_risk(self, player: int, cityLimit: int = 3, inTurns: int = 0) -> int:
        stats = self.get_current_cycle_stats_by_player(player)
        if stats is None:
            return 0

        armyRisk = stats.approximate_fog_army_available_total

        cityTotal = self.get_next_fog_city_amounts(player, cityLimit=cityLimit)

        armyRisk += cityTotal

        gatherOffset = 0

        pTileQueueLists = [self.get_player_gather_queue(pIndex).as_tile_list(includeOnesAndZeros=False) for pIndex in stats.players]

        if inTurns > 0:
            remainingCycleTime = 50 - (self.map.turn % 50)
            enScores = self.get_current_team_scores_by_player(player)
            for i in range(inTurns):
                if (i + remainingCycleTime) & 1 == 0:
                    armyRisk += min(cityLimit, enScores.cityCount)

                if i > remainingCycleTime:
                    # TODO neither of these seemed right, the heck? we already have the gather offset here, why would we ALSO increment the full thing...?
                    # armyRisk += inTurns - remainingCycleTime
                    # armyRisk += cityTotal  # This was DEFINITELY wrong, as it doubled the amount of army we gathered from cities, lmao
                    gatherOffset += 1
                    remainingCycleTime += 50

                for tList in pTileQueueLists:
                    if i < len(tList):
                        armyRisk += tList[i] - 1 + gatherOffset

        return armyRisk

    def get_next_fog_city_amounts(self, player: int, cityLimit: int) -> int:
        """Returns the amount of army expected to be gatherable from up to cityLimit fog cities RIGHT NOW."""

        cycleStats = self.get_current_cycle_stats_by_player(player)
        scores = self.current_team_scores[self._team_lookup_by_player[player]]

        # TODO replace this with a queue system for cities too, instead.
        totalAmt = cycleStats.approximate_fog_city_army

        cityCount = scores.cityCount
        if cityCount <= cityLimit:
            return max(0, totalAmt - 3 * cityCount)

        amtPerCity = totalAmt // cityCount

        return amtPerCity * cityLimit

    def notify_army_moved(self, army: Army):
        tile = army.tile
        if not army.visible and army.path:
            logbook.info(f"OT: Army Moved handler! Tile {repr(tile)}")
            self._moves_into_fog.append(army)

    def even_or_up_on_cities(self, againstPlayer: int = -2) -> bool:
        """

        @param againstPlayer:
        @return:
        """

        return self.up_on_cities(againstPlayer=againstPlayer, byNumber=0)

    def up_on_cities(self, againstPlayer: int = -2, byNumber: int = 1) -> bool:
        """

        @param againstPlayer:
        @param byNumber: emptyVal 1, the offset to subtract from our cities before comparing greater or equal.
        So, 2 cities vs 2 cities returns False with byNumber 1, True for byNumber 0.
        @return:
        """
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer

        if againstPlayer == -1:
            return True

        ourStats = self.map.get_team_stats(self.map.player_index)

        enStats = self.map.get_team_stats(againstPlayer)

        return ourStats.cityCount - byNumber >= enStats.cityCount

    def winning_on_economy(self, byRatio: float = 1.0, cityValue: int = 25, againstPlayer: int = -2, offset: int = 0) -> bool:
        """

        @param byRatio:
        @param cityValue:
        @param againstPlayer:
        @param offset: Positive means more likely to return true, negative is less. Value in extra 'tiles' contributed.
        @return:
        """
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer
        if againstPlayer == -1:
            return True

        ourStats = self.map.get_team_stats(self.map.player_index)

        enStats = self.map.get_team_stats(againstPlayer)

        playerEconValue = (ourStats.tileCount + ourStats.cityCount * cityValue) + offset
        oppEconValue = (enStats.tileCount + enStats.cityCount * cityValue) * byRatio
        return playerEconValue >= oppEconValue

    def winning_on_tiles(self, byRatio: float = 1.0, againstPlayer: int = -2, offset: int = 0) -> bool:
        """

        @param byRatio:
        @param againstPlayer:
        @param offset: Positive means more likely to return true, negative is less. Value in extra 'tiles' contributed.
        @return:
        """

        return self.winning_on_economy(byRatio=byRatio, againstPlayer=againstPlayer, cityValue=0, offset=offset)

    def get_tile_differential(self, againstPlayer: int = -2) -> int:
        """
        Positive number means we're ahead, negative number means we're behind.
        @param againstPlayer:
        @return:
        """
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer
        if againstPlayer == -1:
            return True

        ourStats = self.map.get_team_stats(self.map.player_index)

        enStats = self.map.get_team_stats(againstPlayer)

        return ourStats.tileCount - enStats.tileCount

    def winning_on_army(self, byRatio: float = 1.0, useFullArmy: bool = False, againstPlayer: int = -2, offset: int = 0) -> bool:
        """

        @param byRatio:
        @param useFullArmy:
        @param againstPlayer:
        @param offset:
        @return:
        """
        if againstPlayer == -2:
            againstPlayer = self.targetPlayer
        if againstPlayer == -1:
            return True

        ourStats = self.map.get_team_stats(self.map.player_index)

        enStats = self.map.get_team_stats(againstPlayer)

        targetArmy = enStats.standingArmy
        playerArmy = ourStats.standingArmy

        if useFullArmy:
            targetArmy = enStats.score
            playerArmy = ourStats.score

        winningOnArmy = playerArmy + offset >= targetArmy * byRatio
        logbook.info(
            f"winning_on_army({byRatio}): playerArmy {playerArmy} >= targetArmy {targetArmy} (weighted {targetArmy * byRatio:.1f}) ?  {winningOnArmy}")
        return winningOnArmy

    def get_team_annihilated_fog(self, team: int) -> int:
        if team == -1:
            return 0

        return self.get_team_annihilated_fog_by_player(self._players_lookup_by_team[team][0])

    def get_team_annihilated_fog_by_player(self, player: int) -> int:
        if player == -1:
            return 0

        currentTeamStats = self.get_current_team_scores_by_player(player)
        playerObj = self.map.players[player]

        return self._get_team_annihilated_fog_internal(currentTeamStats, playerObj)

    def _get_team_annihilated_fog_internal(self, currentTeamStats: TeamStats, playerObj: Player) -> int:
        teamAnnihilatedFog = 0 - currentTeamStats.fightingDiff
        if self.map.is_player_on_team_with(self.map.player_index, playerObj.fighting_with_player):
            # then we captured their stuff?
            ourStats = self.map.players[playerObj.fighting_with_player]
            ourFightingDiff = ourStats.actualScoreDelta - ourStats.expectedScoreDelta
            teamAnnihilatedFog += ourFightingDiff

        return teamAnnihilatedFog

    def _validate_army_totals(self, curTurnScores: TeamStats, currentCycleStats: CycleStatsData):
        team = currentCycleStats.team
        sumArmy = 0

        for player in currentCycleStats.players:
            playerSumArmy = 0
            for tile in self.map.players[player].tiles:
                if tile.visible:
                    playerSumArmy += tile.army

            playerSumArmy += self.get_player_gather_queue(player).total_sum

            logbook.info(f'Validating team {team} totals, p{player}: {playerSumArmy}')
            sumArmy += playerSumArmy

        sumWithFog = sumArmy + currentCycleStats.approximate_fog_city_army + currentCycleStats.approximate_fog_army_available_total

        logbook.info(f'Validating team {team} totals, sumArmy {sumArmy} total {sumWithFog}/{curTurnScores.score} (fog {currentCycleStats.approximate_fog_army_available_total}, city {currentCycleStats.approximate_fog_city_army})')

        while sumWithFog < curTurnScores.score:
            if self.view_info:
                self.view_info.add_info_line(f'FIX TM{team} sumWithFog {sumWithFog} < score {curTurnScores.score} (fog {currentCycleStats.approximate_fog_army_available_total}, city {currentCycleStats.approximate_fog_city_army})')
                self.view_info.add_info_line("fixme")
                self.view_info.add_info_line("fixme")
            if currentCycleStats.approximate_fog_army_available_total < 0:
                sumWithFog -= currentCycleStats.approximate_fog_army_available_total
                currentCycleStats.approximate_fog_army_available_total = 0
            elif currentCycleStats.approximate_fog_city_army < curTurnScores.cityCount:
                sumWithFog -= currentCycleStats.approximate_fog_city_army
                sumWithFog += curTurnScores.cityCount
                currentCycleStats.approximate_fog_city_army = curTurnScores.cityCount
            else:
                currentCycleStats.approximate_fog_army_available_total += curTurnScores.score - sumWithFog
                sumWithFog = curTurnScores.score

            if self.view_info:
                self.view_info.add_info_line(f'FIXED OT {team} -> sumWithFog {sumWithFog} score {curTurnScores.score} - fog {currentCycleStats.approximate_fog_army_available_total}, city {currentCycleStats.approximate_fog_city_army}')

    def send_general_distance_notification(self, maxDist: int, tile: Tile, generalConfidence: bool):
        for notification in self.outbound_emergence_notifications:
            notification(maxDist, tile, generalConfidence)

    def get_team_unknown_city_count_by_player(self, player: int) -> int:
        """
        Gets the number of cities the players TEAM has that we have never had vision of yet (so basically the number of undiscovered obstacles that are cities).
        Excludes fog-guess cities.

        @param player:
        @return:
        """
        team = self.get_current_team_scores_by_player(player)
        unkCount = team.cityCount
        for pIdx in team.livingPlayers:
            p = self.map.players[pIdx]
            # general doesn't count
            unkCount -= 1
            for city in p.cities:
                if city.discovered and not city.isTempFogPrediction:
                    unkCount -= 1

        return unkCount
