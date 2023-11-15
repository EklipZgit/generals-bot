from __future__ import annotations

import logging
import typing
from collections import deque

from ArmyTracker import Army
from StrategyModels import CycleStatsData, PlayerMoveCategory
from ViewInfo import ViewInfo, TargetStyle
from base.client.map import MapBase, TeamStats, Tile, Player, PLAYER_CHAR_BY_INDEX

ENABLE_DEBUG_ASSERTS = False

class OpponentTracker(object):
    def __init__(self, map: MapBase, viewInfo: ViewInfo | None = None):
        self.map: MapBase = map
        self.team_score_data_history: typing.Dict[int, typing.Dict[int, TeamStats | None]] = {}
        self.current_team_scores: typing.Dict[int, TeamStats | None] = {}
        """Track the current (or during scan, last turn) data for diffing what happened since last turn"""

        self.last_team_scores: typing.Dict[int, TeamStats | None] = {}
        """Track the last (or during scan, two turns ago) data for diffing what happened since two turns ago, useful for things like city changes since army increments only tick on even turns."""

        self.team_cycle_stats_history: typing.Dict[int, typing.Dict[int, CycleStatsData | None]] = {}
        self.current_team_cycle_stats: typing.Dict[int, CycleStatsData] = {}

        self.assumed_player_average_tile_values: typing.Dict[int, float] = {}
        """The assumed average value of land the player owns, used when looking at attacks that happen against the player in the fog, whether by us or someone else."""

        self.last_player_move_type: typing.Dict[int, PlayerMoveCategory] = {}

        rawTeams = self.map.teams
        if rawTeams is None:
            rawTeams = [i for i, p in enumerate(self.map.players)]

        self._team_indexes = []

        self._team_lookup_by_player: typing.List[int] = MapBase.get_teams_array(map)
        self._players_lookup_by_team: typing.Dict[int, typing.List[int]] = {}

        self._gather_queues_by_player: typing.Dict[int, deque[int]] = {}
        self._emergences: typing.List[typing.Tuple[Army, int]] = []
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
                        self._gather_queues_by_player[player.index] = deque()
                        self.last_player_move_type[player.index] = PlayerMoveCategory.FogGather

                self.team_score_data_history[team] = {}
                turn0Stats = CycleStatsData(team, self.get_team_players(team))
                self.team_score_data_history[team][0] = TeamStats(0, 0, 0, len(turn0Stats.players), 0, 0)
                self.current_team_cycle_stats[team] = turn0Stats
                self.team_cycle_stats_history[team] = {}
                self._team_indexes.append(team)
                self.current_team_scores[team] = None
                self.last_team_scores[team] = None

    def get_last_cycle_stats_per_team(self) -> typing.Dict[int, CycleStatsData]:
        lastCycleEndTurn = self.get_last_cycle_end_turn()
        ret = {}
        for team in self._team_indexes:
            lastCycleStats = self.team_cycle_stats_history[team].get(lastCycleEndTurn, None)
            ret[team] = lastCycleStats

        return ret

    def analyze_turn(self, targetPlayer: int):
        self.current_differential_vs_us_by_team: typing.Dict[int, CycleStatsData]

        for player in self.map.players:
            # if we don't figure out anything else, then probably a fog gather. Default to that at start of each turn.
            self.last_player_move_type[player.index] = PlayerMoveCategory.FogGather

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
                # do the final pass on the current cycle data and then start a new cycle.
                self.team_score_data_history[team][self.map.turn] = curTurnTeamScore
                if teamStats is not None:
                    self.team_cycle_stats_history[team][self.map.turn] = teamStats.clone()

            self.last_team_scores[team] = self.current_team_scores[team]
            self.current_team_scores[team] = curTurnTeamScore

        self._emergences = []
        self._moves_into_fog = []
        self._revealed = set()
        self._vision_losses = set()

        self.recalculate_average_tile_values()

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

    def notify_emerged_army(self, army: Army, emergenceAmount: int):
        """
        Call this when an army emerges so that we can reduce the tracked expected fog gather amounts.

        @param army:
        @param emergenceAmount:
        @return:
        """
        em = (army, emergenceAmount)
        logging.info(f'OppTrack EM: queued {repr(em)}')
        self._emergences.append(em)

    def notify_player_tile_revealed(self, tile: Tile):
        """
        Call this when a tile that was not previously owned by a team is revealed from fog as owned by that team.

        @param tile:
        @return:
        """
        logging.info(f'OppTrack V+: queued {repr(tile)}')

        self._revealed.add(tile)

    def notify_player_tile_vision_lost(self, tile: Tile):
        if tile.player >= 0:
            logging.info(f'OppTrack V-: queued {repr(tile)}')
            self._vision_losses.add(tile)

    def dump_to_string_data(self) -> str:
        data = []
        for i in range(3):
            cycleTurn = self.get_last_cycle_end_turn(cyclesToGoBack=i)
            for team in self._team_indexes:
                stats = self.team_score_data_history[team].get(cycleTurn, None)
                if stats is not None:
                    data.append(f'ot_{team}_c_{cycleTurn}_tileCount={stats.tileCount}')
                    data.append(f'ot_{team}_c_{cycleTurn}_score={stats.score}')
                    data.append(f'ot_{team}_c_{cycleTurn}_standingArmy={stats.standingArmy}')
                    data.append(f'ot_{team}_c_{cycleTurn}_cityCount={stats.cityCount}')
                    data.append(f'ot_{team}_c_{cycleTurn}_fightingDiff={stats.fightingDiff}')
                    data.append(f'ot_{team}_c_{cycleTurn}_unexplainedTileDelta={stats.unexplainedTileDelta}')

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
                data.append(f'ot_{team}_stats_approximate_fog_city_army={stats.approximate_fog_city_army}')

        tileCountsByPlayer = self.get_player_fog_tile_count_dict()

        for player, tileCounts in tileCountsByPlayer.items():
            if player == self.map.player_index or player in self.map.teammates:
                continue
            playerFogSubtext = "|".join([f'{n}x{tileSize}' for tileSize, n in sorted(tileCounts.items(), reverse=True)])
            data.append(f'ot_{PLAYER_CHAR_BY_INDEX[player]}_tcs={playerFogSubtext}')

        return '\n'.join(data)

    def load_from_map_data(self, data: typing.Dict[str, str]):
        for i in range(5):
            cycleTurn = self.get_last_cycle_end_turn_raw(cyclesToGoBack=i)
            if cycleTurn is None:
                break
            for team in self._team_indexes:
                stats = TeamStats(0, 0, 0, 0, 0, 0)
                self.team_score_data_history[team][cycleTurn] = stats
                if f'ot_{team}_c_{cycleTurn}_tileCount' in data:
                    stats.tileCount = int(data[f'ot_{team}_c_{cycleTurn}_tileCount'])
                    stats.score = int(data[f'ot_{team}_c_{cycleTurn}_score'])
                    stats.standingArmy = int(data[f'ot_{team}_c_{cycleTurn}_standingArmy'])
                    stats.cityCount = int(data[f'ot_{team}_c_{cycleTurn}_cityCount'])
                    stats.fightingDiff = int(data[f'ot_{team}_c_{cycleTurn}_fightingDiff'])
                    stats.unexplainedTileDelta = int(data[f'ot_{team}_c_{cycleTurn}_unexplainedTileDelta'])

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
                stats.approximate_fog_city_army = int(data[f'ot_{team}_stats_approximate_fog_city_army'])

            self.calculate_cycle_stats(team, self.map.get_team_stats_by_team_id(team))

        for player in self.map.players:
            if player.index == self.map.player_index or player.index in self.map.teammates:
                continue

            if f'ot_{PLAYER_CHAR_BY_INDEX[player.index]}_tcs' in data:
                self._gather_queues_by_player[player.index].clear()
                countsSplit = data[f'ot_{PLAYER_CHAR_BY_INDEX[player.index]}_tcs'].split('|')

                for sizeCountStr in countsSplit:
                    countStr, sizeStr = sizeCountStr.strip().strip('s').split('x')
                    size = int(sizeStr)
                    for i in range(int(countStr)):
                        self._gather_queues_by_player[player.index].append(size)

    def calculate_cycle_stats(self, team: int, curTurnScores: TeamStats) -> CycleStatsData | None:
        lastCycleEndTurn = self.get_last_cycle_end_turn()
        if lastCycleEndTurn is None:
            return None

        isCycleEnd = self.map.is_army_bonus_turn
        isCityBonus = self.map.is_city_bonus_turn

        lastTurnScores = self.current_team_scores[team]
        currentCycleStats = self.current_team_cycle_stats[team]

        if currentCycleStats is None:
            currentCycleStats = self.initialize_cycle_stats(team)

        lastCycleScores = self.team_score_data_history[team].get(lastCycleEndTurn, None)
        lastCycleStats = self.team_cycle_stats_history[team].get(lastCycleEndTurn, None)

        self._handle_emergences(currentCycleStats)
        self._handle_moves_into_fog(currentCycleStats)

        self._update_team_cycle_stats_based_on_turn_deltas(currentCycleStats, currentTeamStats=curTurnScores, lastTurnTeamStats=lastTurnScores)

        self._handle_reveals(currentCycleStats)
        self._handle_vision_losses(currentCycleStats)

        self._update_team_cycle_stats_relative_to_last_cycle(currentCycleStats, currentTeamStats=curTurnScores, lastCycleScores=lastCycleScores)

        if isCityBonus:
            self._include_city_bonus(currentCycleStats)

        if isCycleEnd:
            self.team_score_data_history[team][self.map.turn] = curTurnScores
            self.team_cycle_stats_history[team][self.map.turn] = currentCycleStats

            # reset certain things after recording the final cycle stuff

            currentCycleStats = self._start_next_cycle(currentCycleStats, lastCycleStats=currentCycleStats, currentTeamStats=curTurnScores, lastCycleTeamStats=lastCycleScores)
            self.current_team_cycle_stats[currentCycleStats.team] = currentCycleStats

        self._check_missing_fog_gather_tiles(currentCycleStats)

        return currentCycleStats

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
        return self._players_lookup_by_team[team]

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

        if player.unexplainedTileDelta > 0 and currentTeamStats.unexplainedTileDelta >= 0:
            teamAnnihilatedFog = 0 - currentTeamStats.fightingDiff

            if teamAnnihilatedFog > 0:
                logging.info(f'Assuming p{player.index} attacked another player under fog, annihilated {playerAnnihilated}.')
                # player is fighting a player in the fog and capped their tile
                self._assume_fog_player_capture_move(player, currentCycleStats)
            elif teamAnnihilatedFog < 0:
                logging.error(f'This should be impossible unless we mis-counted cities... p{player.index} captured ally tile under fog (or ffa player capture?), annihilated {playerAnnihilated}.')
                # they must have captured someone or taken an allied tile
                self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=True)
            else:
                logging.info(f'Assuming p{player.index} was under attack under the fog, annihilated {playerAnnihilated}.')
                # must be neutral capture
                self._assume_fog_neutral_capture_move(player, currentCycleStats)
            #
            # if teamAnnihilatedFog != 0 and self.map.is_player_on_team_with(player.fighting_with_player, player.index):
            #     # then captured a neutral tile, otherwise captured the delta worth of other player fight delta
        elif player.unexplainedTileDelta < 0:
            if currentTeamStats.unexplainedTileDelta < 0:
                logging.info(f'Assuming p{player.index} was under attack under the fog, annihilated {playerAnnihilated}.')
                self._assume_fog_under_attack_move(player, currentCycleStats, tileCapturedBySomeoneElse=True, annihilated=playerAnnihilated)
            else:
                # ally took one of their tiles, and they gathered, so this is also just a fog gather move
                logging.info(f'Assuming p{player.index} had a tile captured by their ally, fog gather move.')
                self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)
        elif playerAnnihilated > 0:
            # player capping neutral city, or something? or being attacked for non-lethal tile damage? Probably no-op here, but lets assume gather move for now.
            logging.info(f'Assuming p{player.index} gathermove because no tile change DESPITE army annihilation of {playerAnnihilated}.')
            self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)
        else:
            logging.info(f'Assuming p{player.index} gathermove based on no detected changes. playerAnnihilated {playerAnnihilated}')
            self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)

    def _check_visible_move(self, player: Player, currentCycleStats: CycleStatsData):
        source: Tile
        dest: Tile
        source, dest = player.last_move
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
        try:
            gatherVal = gatherQueueSource.popleft()

            gatherQueueDest = self.get_player_gather_queue(player.index)
            gatherQueueDest.append(1)

            currentCycleStats.approximate_army_gathered_this_cycle += gatherVal - 1
            currentCycleStats.approximate_fog_army_available_total += gatherVal - 1
            logging.info(f'increasing p{player.index}s gather value by {gatherVal}')
        except IndexError:
            logging.info(f'No gather value to dequeue for p{player.index} ')

        currentCycleStats.moves_spent_gathering_fog_tiles += 1
        self.last_player_move_type[player.index] = PlayerMoveCategory.FogGather

    def _assume_fog_neutral_capture_move(self, player: Player, currentCycleStats: CycleStatsData):
        currentCycleStats.approximate_army_gathered_this_cycle -= 1
        currentCycleStats.approximate_fog_army_available_total -= 1

        self._check_available_fog_army(currentCycleStats)

        currentCycleStats.moves_spent_capturing_fog_tiles += 1
        currentCycleStats.tiles_gained += 1
        gatherQueue = self.get_player_gather_queue(player.index)
        gatherQueue.append(1)

        self.last_player_move_type[player.index] = PlayerMoveCategory.FogCapture

    def _assume_fog_player_capture_move(self, player: Player, currentCycleStats: CycleStatsData):
        playerAnnihilatedFog = player.expectedScoreDelta - player.actualScoreDelta
        currentCycleStats.army_annihilated_fog += playerAnnihilatedFog
        currentCycleStats.approximate_army_gathered_this_cycle -= playerAnnihilatedFog + 1
        currentCycleStats.approximate_fog_army_available_total -= playerAnnihilatedFog + 1

        self._check_available_fog_army(currentCycleStats)

        currentCycleStats.moves_spent_capturing_fog_tiles += 1
        currentCycleStats.tiles_gained += 1
        gatherQueue = self.get_player_gather_queue(player.index)
        gatherQueue.append(1)

        self.last_player_move_type[player.index] = PlayerMoveCategory.FogCapture

    def _assume_fog_under_attack_move(self, player: Player, currentCycleStats: CycleStatsData, tileCapturedBySomeoneElse: bool, annihilated: int):
        if tileCapturedBySomeoneElse:
            currentCycleStats.tiles_gained -= 1
        else:
            self._assume_fog_gather_move(player, currentCycleStats, gatheringAllyTile=False)
        # if player.fighting_with_player != -1:

        if annihilated > self.assumed_player_average_tile_values[player.index] * 1.5:
            # then we assume they used gathered army to block the attack and weren't just having land taken.
            currentCycleStats.approximate_fog_army_available_total -= annihilated
            currentCycleStats.approximate_army_gathered_this_cycle -= annihilated
        else:
            self._remove_queued_gather_closest_to_amount(player.index, annihilated)

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
                    logging.info(f"PLAYER GATHERED ALL TILES? CALCED {teamAverageUngatheredTileVal} VS OUR EXPECTED 1.0")
                    self.assumed_player_average_tile_values[player.index] = 1.0

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

    def get_last_cycle_stats_by_team(self, team: int) -> CycleStatsData | None:
        lastCycleTurn = self.get_last_cycle_end_turn()
        return self.team_cycle_stats_history[team].get(lastCycleTurn, None)

    def get_player_gather_queue(self, player: int) -> deque[int]:
        return self._gather_queues_by_player[player]

    def _update_team_cycle_stats_relative_to_last_cycle(
        self,
        currentCycleStats,
        currentTeamStats,
        lastCycleScores
    ):
        # in theory this should be kept up to date
        calculatedTilesGained = currentTeamStats.tileCount - lastCycleScores.tileCount
        if calculatedTilesGained != currentCycleStats.tiles_gained:
            logging.info(f'team[{currentCycleStats.team}]: calculatedTilesGained {calculatedTilesGained} != currentCycleStats.tiles_gained {currentCycleStats.tiles_gained}, updating...')
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
        nextStats.approximate_fog_city_army = currentCycleStats.approximate_fog_city_army
        fogTileCount, fogArmyAmount, fogCityCount, playerCountAliveOnTeam = self.calculate_team_fog_tile_data(currentCycleStats.team)
        # fog cities also get army bonus, and this is cycle bonus turn.
        nextStats.approximate_fog_city_army += fogCityCount

        for player in currentCycleStats.players:
            gatherQueue = self.get_player_gather_queue(player)
            newQueue = deque()
            while len(gatherQueue) > 0:
                next = gatherQueue.popleft()
                newQueue.append(next + 1)

            self._gather_queues_by_player[player] = newQueue

        return nextStats

    def _handle_emergences(self, currentCycleStats: CycleStatsData):
        for army, emergence in self._emergences:
            if army.tile.delta.gainedSight:
                continue  # handled by revealed handler
            if emergence < 0:
                emergence = abs(emergence) - 1

            if army.player in currentCycleStats.players:
                self._execute_emergence(currentCycleStats, army.tile, emergence, army.player)

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

    def _handle_reveals(self, currentCycleStats: CycleStatsData):
        for tile in self._revealed:
            if tile.player not in currentCycleStats.players:
                continue

            fogTileCount, fogArmyAmount, fogCityCount = self.calculate_player_fog_tile_data(tile.player)
            gathQueue = self.get_player_gather_queue(tile.player)
            armyThresh = 1
            if len(gathQueue) > 0:
                armyThresh = gathQueue[0]

            armyToUse = max(abs(tile.delta.unexplainedDelta), tile.army)

            if tile.isCity or tile.isGeneral:
                logging.info(f'V+: {repr(tile)} - team[{currentCycleStats.team}] city/gen revealed, reducing fog city amt by that.')
                currentCycleStats.approximate_fog_city_army -= armyToUse
            elif len(gathQueue) > fogTileCount - fogCityCount:
                logging.info(f'V+: {repr(tile)} - removing p{tile.player} queued gather closest to army {armyToUse}, len(gathQueue) {len(gathQueue)} > fogTileCount {fogTileCount} - fogCityCount {fogCityCount}')
                self._remove_queued_gather_closest_to_amount(tile.player, armyToUse)

            if armyToUse > armyThresh:
                logging.info(f'V+: {repr(tile)} - team[{currentCycleStats.team}] large tile revealed {armyToUse} > {armyThresh}, reducing fog army by that.')
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
            if len(playerGathQueue) > 0:
                gathCutoff = playerGathQueue[0] * 1.5

            if tile.isCity or tile.isGeneral:
                logging.info(f'V-: {repr(tile)} - p{tile.player} city/gen vision lost, adding that amount to fog city army')
                # TODO do we actually want this? Feels like we should only track this for unknown cities, since we're
                #  already incrementing THESE cities directly as we know where they are, and armyTracker fog emergence
                #  already reduces them...?
                currentCycleStats.approximate_fog_city_army += tile.army - 1
            elif tile.army > gathCutoff:
                # then immediately count this as gathered army and put a 1 in the queue, instead.
                # TODO track BFS movement through the fog of this amount instead of immediately making it available as
                #  a flank threat instead, since we know where it last was...?
                # TODO Why do this at all? Make them spend one turn gathering these large tiles to include them in army, why not...?
                logging.info(f'V-: {repr(tile)} - p{tile.player} large tile {tile.army} > gathCutoff {gathCutoff:.1f}, so counting towards fog army. Counting tile as gatherable 1')
                currentCycleStats.approximate_fog_army_available_total += tile.army - 1

                # They DIDNT gather this this cycle (or if they did it was already recorded) so DONT do the below.
                # currentCycleStats.approximate_army_gathered_this_cycle += tile.army - 1

                playerGathQueue.append(1)
            else:
                logging.info(f'V-: {repr(tile)} - p{tile.player} vision lost, adding {tile.army} to the gather queue.')
                self.insert_amount_into_player_gather_queue(tile.player, tile.army)

    def _remove_queued_gather_closest_to_amount(self, player: int, tileAmount: int):
        q = self.get_player_gather_queue(player)

        if len(q) == 0:
            return

        newQ = deque()
        while len(q) > 1 and q[0] > tileAmount:
            nextVal = q.popleft()
            newQ.append(nextVal)

        valAnnihilated = q.popleft()
        if valAnnihilated != tileAmount:
            logging.info(
                f'RemoveGath: p{player} didnt have tile of tileAmount {tileAmount}, dropping {valAnnihilated} from queue instead...?')

        while len(q) > 0:
            nextVal = q.popleft()
            newQ.append(nextVal)

        self._gather_queues_by_player[player] = newQ

    def insert_amount_into_player_gather_queue(self, player: int, tileAmount: int):
        q = self.get_player_gather_queue(player)

        if len(q) == 0:
            return

        newQ = deque()
        while len(q) > 1 and q[0] > tileAmount:
            nextVal = q.popleft()
            newQ.append(nextVal)

        newQ.append(tileAmount)

        while len(q) > 0:
            nextVal = q.popleft()
            newQ.append(nextVal)

        self._gather_queues_by_player[player] = newQ

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

    def _check_available_fog_army(self, currentCycleStats: CycleStatsData):
        fogTileCount, fogArmyAmount, fogCityCount, playerCountAliveOnTeam = self.calculate_team_fog_tile_data(currentCycleStats.team)

        if fogCityCount == 0:
            return

        fogCityOriginalAmount = currentCycleStats.approximate_fog_city_army
        armyPerFogCity = fogCityOriginalAmount // fogCityCount
        if armyPerFogCity <= 0:
            return

        if currentCycleStats.approximate_fog_army_available_total <= 0:
            for i in range(fogCityCount):
                if currentCycleStats.approximate_fog_army_available_total <= 0:
                    logging.info(
                        f'FogCheck: team[{currentCycleStats.team}] approximate_fog_army_available_total {currentCycleStats.approximate_fog_army_available_total} <= 0, pulling from fog cities which each are estimated at armyPerFogCity {armyPerFogCity}')

                    currentCycleStats.approximate_fog_army_available_total += armyPerFogCity
                    currentCycleStats.approximate_fog_city_army -= armyPerFogCity

    def get_player_fog_tile_count_dict(self) -> typing.Dict[int, typing.Dict[int, int]]:
        gatherValueCountsByPlayer = {}
        for player in self.map.players:
            playerGathValueCounts = {}
            gatherValueCountsByPlayer[player.index] = playerGathValueCounts
            queue = self.get_player_gather_queue(player.index)
            for gatherTile in queue:
                curCount = playerGathValueCounts.get(gatherTile, 0)
                playerGathValueCounts[gatherTile] = curCount + 1

        return gatherValueCountsByPlayer

    def _check_missing_fog_gather_tiles(self, currentCycleStats: CycleStatsData):
        for playerIdx in currentCycleStats.players:
            playerFogTileCount, playerFogArmyAmount, playerFogCityCount = self.calculate_player_fog_tile_data(playerIdx)
            # we dont include their cities in the gatherable tile list
            playerFogGathTileCount = playerFogTileCount - playerFogCityCount
            queue = self.get_player_gather_queue(playerIdx)
            while len(queue) < playerFogGathTileCount:
                logging.info(f'CheckMissingFogGath: p{playerIdx} team[{currentCycleStats.team}] is missing fog tiles (q {len(queue)} vs actual {playerFogGathTileCount})...? Adding a 1')
                queue.append(1)

    def get_current_cycle_stats_by_player(self, player: int) -> CycleStatsData:
        return self.current_team_cycle_stats[self._team_lookup_by_player[player]]

    def _execute_emergence(self, currentCycleStats: CycleStatsData, tile: Tile, emergence: int, player: int = -2):
        if player == -2:
            player = tile.player

        teamScores = self.current_team_scores[currentCycleStats.team]
        teamTotalFogEmergenceEst = currentCycleStats.approximate_fog_army_available_total + currentCycleStats.approximate_fog_city_army - 5 * teamScores.cityCount

        thresh = teamTotalFogEmergenceEst * 0.85

        fullFogReset = False
        if emergence > thresh:
            logging.info(
                f'E+: fullFogReset - emergence {emergence} > thresh {thresh:.1f} (based on teamTotalFogEmergenceEst {teamTotalFogEmergenceEst})')
            if emergence > teamTotalFogEmergenceEst:
                logging.error(
                    f'UNDERESTIMATED BY {emergence - teamTotalFogEmergenceEst}! E+: fullFogReset - emergence {emergence} > thresh {thresh:.1f} (based on teamTotalFogEmergenceEst {teamTotalFogEmergenceEst})')
                if self.view_info is not None:
                    self.view_info.addAdditionalInfoLine(f'UNDERESTIMATED BY {emergence - teamTotalFogEmergenceEst}! E+: fullFogReset - emergence {emergence} > thresh {thresh:.1f} (based on teamTotalFogEmergenceEst {teamTotalFogEmergenceEst})')
                    self.view_info.add_targeted_tile(tile, TargetStyle.ORANGE)
            fullFogReset = True

        logging.info(
            f'E+: {repr(tile)} - p{player} team[{currentCycleStats.team}] emergence {emergence} reducing approximate_fog_army_available_total')

        currentCycleStats.approximate_fog_army_available_total -= emergence

        while currentCycleStats.approximate_fog_army_available_total < 0 and currentCycleStats.approximate_fog_city_army > 1:
            logging.info(
                f'  E+: {repr(tile)} - p{player} team[{currentCycleStats.team}] emergence {emergence} brought approximate_fog_army_available_total {currentCycleStats.approximate_fog_army_available_total} below 0, using city values')
            currentCycleStats.approximate_fog_army_available_total += currentCycleStats.approximate_fog_city_army // 2
            currentCycleStats.approximate_fog_city_army -= currentCycleStats.approximate_fog_city_army // 2

        if fullFogReset:
            if currentCycleStats.approximate_fog_army_available_total + currentCycleStats.approximate_fog_city_army - 6 * teamScores.cityCount > teamTotalFogEmergenceEst * 0.1:
                currentCycleStats.approximate_fog_army_available_total = 0
                # TODO better estimation of city distances to gather path
                currentCycleStats.approximate_fog_city_army = 5 * teamScores.cityCount + max(0, (10 * teamScores.cityCount - 2))
                # TODO figure out how many incorrect assumption gathered tiles we assumed and put them back in the queue...?

        if currentCycleStats.approximate_fog_army_available_total < 0:
            currentCycleStats.approximate_fog_army_available_total = 0
        if currentCycleStats.approximate_fog_city_army < 0:
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

    def get_approximate_fog_army_risk(self, player: int, cityLimit=3) -> int:
        stats = self.get_current_cycle_stats_by_player(player)
        if stats is None:
            return 0

        armyRisk = stats.approximate_fog_army_available_total

        cityTotal = self.get_next_fog_city_amounts(player, cityLimit=cityLimit)

        armyRisk += cityTotal

        return armyRisk

    def get_next_fog_city_amounts(self, player: int, cityLimit: int) -> int:
        cycleStats = self.get_current_cycle_stats_by_player(player)
        scores = self.current_team_scores[self._team_lookup_by_player[player]]

        # TODO replace this with a queue system, instead.
        totalAmt = cycleStats.approximate_fog_city_army

        cityCount = (scores.cityCount + 1)
        if cityCount <= cityLimit:
            return max(0, totalAmt - 3 * cityCount)

        amtPerCity = totalAmt // cityCount

        return amtPerCity * cityLimit

    def notify_army_moved(self, army: Army):
        tile = army.tile
        if not army.visible and army.path:
            logging.info(f"OT: Army Moved handler! Tile {repr(tile)}")
            self._moves_into_fog.append(army)
