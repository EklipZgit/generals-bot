"""
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Map: Objects for representing Generals IO Map and Tiles
"""
from __future__ import annotations

from copy import deepcopy
from base.client.tile import *

import logbook
import random
import typing
import uuid
from collections import deque

import BotLogging
from Interfaces import MapMatrixInterface, TileSet
MODIFIER_TORUS = 7
MODIFIER_WATCHTOWER = 6

MAX_ALLY_SPAWN_DISTANCE = 10

ENABLE_DEBUG_ASSERTS = False

LEFT_GAME_FFA_CAPTURE_LIMIT = 50
"""How many turns after an FFA player disconnects that you can capture their gen."""


_REPLAY_URLS = {
    'na': "http://generals.io/replays/",
    'eu': "http://eu.generals.io/replays/",
}

T = typing.TypeVar('T')


class TeamStats(object):
    def __init__(self, tileCount: int, score: int, standingArmy: int, cityCount: int, fightingDiff: int, unexplainedTileDelta: int, teamId: int, teamPlayers: typing.List[int], livingPlayers: typing.List[int], turn: int = 0):
        self.tileCount: int = tileCount
        self.score: int = score
        self.standingArmy: int = standingArmy
        self.cityCount: int = cityCount
        self.fightingDiff: int = fightingDiff
        self.unexplainedTileDelta: int = unexplainedTileDelta
        self.teamId: int = teamId
        self.teamPlayers: typing.List[int] = teamPlayers
        self.livingPlayers: typing.List[int] = livingPlayers
        self.turn: int = turn

    def __str__(self) -> str:
        return f'{self.score} {self.tileCount}t {self.cityCount}c  {self.standingArmy}standingArmy {self.fightingDiff}fightingDiff {self.unexplainedTileDelta}unexTileDelta'


class Player(object):
    def __init__(self, player_index: int):
        self.cities: typing.List[Tile] = []
        self.general: Tile | None = None
        self.index: int = player_index
        self.stars = 0
        self.score: int = 0
        self.team: int = player_index

        self.scoreDelta: int = 0
        """The player score delta since last move."""

        self.tileDelta: int = 0
        """The player tile delta since last move."""

        self.unexplainedTileDelta: int = 0
        """The tile delta unexplained by known moves."""

        self.tiles: typing.List[Tile] = []
        self.tileCount: int = 0
        self.standingArmy: int = 0
        self.visibleStandingArmy: int = 0
        self.cityCount: int = 1
        self.lastCityCount: int = 1
        self.cityLostTurn: int = 0
        self.cityGainedTurn: int = 0
        self.delta25tiles: int = 0
        self.delta25score: int = 0
        self.actualScoreDelta: int = 0
        self.expectedScoreDelta: int = 0
        """The delta expected if no annihilations were to take place based on city counts and army bonuses"""
        self.knownScoreDelta: int = 0
        """The score delta that we understood including expected score delta and visible annihilations"""

        self.fighting_with_player: int = -1
        """
        If player score deltas show players fighting with each other on this turn, then this will be set. 
        If multiple players are found that all match deltas, then tiebreaks are performed based on recent historical
        fights. If the player is clearly fighting with someone but the deltas dont line up because a third party is
        involved, then this value will be unmodified from previous turn, usually continuing to indicate the last player
        they were already fighting with.
        """

        self.last_move: typing.Tuple[Tile | None, Tile | None, bool] | None = None
        """Populated by the map based on tile and player deltas IF the map can determine FOR SURE what move the player made. (source, dest). One or the other may be null if one can be determined but the other can't."""

        self.dead = False
        """Set to true once a player is killed, or after they disconnect and the 50-turn-disconnect timer expires."""

        self.leftGame = False
        """True after a player has left the game."""

        self.leftGameTurn: int = -1
        """The turn the player left the game. Useful to know how many turns to attempt a capture are left."""

        self.capturedBy: int | None = None
        self.knowsKingLocation: bool = False
        self.knowsAllyKingLocation: bool = False
        self.aggression_factor: int = 0
        """"""
        self.last_seen_move_turn: int = 0
        """True if this player knows the map.player_index players general location. False otherwise."""

    def __str__(self):
        return f'p{self.index}{" (dead)" if self.dead else ""}: tiles {self.tileCount}, cities {self.cityCount}, standingArmy {self.standingArmy}, general {str(self.general)}'


class Score(object):
    def __init__(self, player: int, total: int, tiles: int, dead: bool):
        self.player: int = player
        self.total: int = total
        self.tiles: int = tiles
        self.dead: bool = dead

    @staticmethod
    def from_server_scores(scores_from_server: typing.List[dict]):
        return [
            Score(player, scores_entry['total'], scores_entry['tiles'], scores_entry['dead'])
            for player, scores_entry
            in enumerate(scores_from_server)
        ]

    def __str__(self) -> str:
        return f'p{self.player}{" DEAD" if self.dead else ""} {self.total} {self.tiles}t'


class DistanceMapper:
    def get_distance_between_or_none(self, tileA: Tile, tileB: Tile) -> int | None:
        raise NotImplementedError()

    def get_distance_between(self, tileA: Tile, tileB: Tile) -> int:
        raise NotImplementedError()

    def get_distance_between_or_none_dual_cache(self, tileA: Tile, tileB: Tile) -> int | None:
        raise NotImplementedError()

    def get_distance_between_dual_cache(self, tileA: Tile, tileB: Tile) -> int:
        raise NotImplementedError()

    def get_tile_dist_matrix(self, tile: Tile) -> MapMatrixInterface[int]:
        """Actually returns mapmatrix, but they behave similarly and cant declare mapmatrix here because it uses map as a circular reference."""
        raise NotImplementedError()

    def recalculate(self):
        """Wipe all cached distances."""
        raise NotImplementedError()


class MapBase(object):
    DO_NOT_RANDOMIZE: bool = False
    """Static property to prevent randomizing the tile adjacency matrix."""

    def __init__(self,
                 player_index: int,
                 teams: typing.Union[None, typing.List[int]],  # the players index into this array gives the index of their teammate as the value.
                 user_names: typing.List[str],
                 turn: int,
                 map_grid_y_x: typing.List[typing.List[Tile]],  # dont need to init movable and stuff
                 replay_url: str,
                 replay_id: typing.Union[None, str] = None,
                 modifiers: typing.List[int] | None = None
                 ):
        # Start Data
        self.remainingCycleTurns: int = 0
        self.cycleTurn: int = 0
        self.distance_mapper: DistanceMapper = DistanceMapper()
        self.last_player_index_submitted_move: typing.Tuple[Tile, Tile, bool] | None = None
        self.player_index: int = player_index  # Integer Player Index
        # TODO TEAMMATE
        self.is_2v2: bool = False
        self.teammates: typing.Set[int] = set()
        self.lookouts: typing.Set[Tile] = set()
        self.observatories: typing.Set[Tile] = set()
        self.modifiers_by_id = [False for i in range(30)]
        if modifiers:
            for m in modifiers:
                self.modifiers_by_id[m] = True

        uniqueTeams = set()
        if teams is not None:
            for player, team in enumerate(teams):
                uniqueTeams.add(team)
                if team == teams[self.player_index] and player != self.player_index:
                    self.teammates.add(player)
            if len(uniqueTeams) == 2 and len(teams) == 4:
                self.is_2v2 = True

        self.teams: typing.List[int] | None = teams

        self.usernames: typing.List[str] = user_names  # List of String Usernames
        self.players: typing.List[Player] = [Player(x) for x in range(len(self.usernames))]

        self.team_ids_by_player_index = MapBase._build_teams_array(self)
        for p, t in enumerate(self.team_ids_by_player_index):
            if t != -1:
                self.players[p].team = t
        self._teammates_by_player: typing.List[typing.List[int]] = [[p.index for p in self.players if p.team == t] for t in self.team_ids_by_player_index]
        self._teammates_by_player[-1].append(-1)  # neutrals only teammate is neutral
        self._teammates_by_player_no_self: typing.List[typing.List[int]] = [[p.index for p in self.players if p.team == t if p.index != pIdx] for pIdx, t in enumerate(self.team_ids_by_player_index)]
        self._teammates_by_team = [[p.index for p in self.players if p.team == i] for i in range(max(self.team_ids_by_player_index) + 2)]  # +2 so we have an entry for each time ID AND -1
        self._teammates_by_team[-1].append(-1)  # neutrals only teammate is neutral
        self._team_stats: typing.List[TeamStats | None] = [None for i in range(max(self.team_ids_by_player_index) + 2)]  # +2 so we have an entry for each time ID AND -1
        self.friendly_team: int = self.team_ids_by_player_index[player_index]

        self.pathable_tiles: typing.Set[Tile] = set()
        """Tiles PATHABLE from the general spawn on the map, including neutral cities but not including mountains/undiscovered obstacles"""

        self.reachable_tiles: typing.Set[Tile] = set()
        """
        Tiles REACHABLE from the general spawn on the map, this includes EVERYTHING from pathableTiles but ALSO 
        includes mountains and undiscovered obstacles that are left/right/up/down adjacent to anything in pathableTiles
        """

        self.visible_tiles: typing.Set[Tile] = set()
        """All tiles that are currently visible on the map, as a set."""

        self.unreachable_tiles: typing.Set[Tile] = set()
        """All tiles that are not in reachable tiles."""

        self.unpathable_tiles: typing.Set[Tile] = set()
        """All tiles that are not in pathable tiles."""

        self.non_visible_tiles: typing.Set[Tile] = set()
        """All tiles that are not visible."""

        self.notify_tile_captures = []
        self.notify_tile_deltas = []
        self.notify_city_found = []
        self.notify_tile_discovered = []
        self.notify_tile_vision_changed = []
        self.notify_general_revealed = []
        self.notify_player_captures = []

        # First Game Data
        # self._applyUpdateDiff(data)
        self.rows: int = len(map_grid_y_x)  # Integer Number Grid Rows
        self.cols: int = len(map_grid_y_x[0])  # Integer Number Grid Cols
        self.grid: typing.List[typing.List[Tile]] = map_grid_y_x
        self.army_moved_grid: typing.List[typing.List[bool]] = []
        self.army_emergences: typing.Dict[Tile, typing.Tuple[int, int]] = {}
        """Lookup from Tile to (emergedAmount, emergingPlayer)"""

        # List of 8 Generals (None if not found)
        self.generals: typing.List[typing.Union[Tile, None]] = [
            None
            for x
            in range(16)]

        self.init_grid_movable()

        self.is_city_bonus_turn: bool = turn & 1 == 0
        self.is_army_bonus_turn: bool = turn % 50 == 0
        
        self._turn: int = turn  # Integer Turn # (1 turn / 0.5 seconds)
        # List of City Tiles. Need concept of hidden cities from sim..? or maintain two maps, maybe. one the sim maintains perfect knowledge of, and one for each bot with imperfect knowledge from the sim.
        self.replay_url = replay_url
        self.replay_id = replay_id
        if self.replay_id is None:
            self.replay_id = f'TEST__{str(uuid.uuid4())}'

        self.scores: typing.List[Score] = [Score(x, 0, 0, False) for x in range(16)]  # List of Player Scores

        self.complete: bool = False
        """Game Complete"""

        self.result: bool = False
        """Game Result (True = Won)"""

        self.scoreHistory: typing.List[typing.List[Score] | None] = [None for i in range(50)]
        """Last 50 turns worth of score histories, by player."""

        self.remainingPlayers = 0

        self.resume_data: typing.Dict[str, str] = {}
        """Data for resuming a game in unit test. Unused in normal games."""

        self.modifiers: typing.Set[str] = set()

        self.tiles_by_index: typing.List[Tile] = [None] * (len(map_grid_y_x) * len(map_grid_y_x[0]))
        for tile in self.get_all_tiles():
            self.tiles_by_index[tile.tile_index] = tile

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f'p{self.player_index} t{self.turn}'

    @property
    def turn(self) -> int:
        return self._turn

    @turn.setter
    def turn(self, val: int):
        self.cycleTurn = val % 50
        self.remainingCycleTurns = 50 - self.cycleTurn

        if val & 1 == 0:
            self.is_city_bonus_turn = True
            self.is_army_bonus_turn = self.cycleTurn == 0
        else:
            self.is_army_bonus_turn = False
            self.is_city_bonus_turn = False

        self._turn = val

    def __getstate__(self):
        state = self.__dict__.copy()

        if 'notify_tile_captures' in state:
            del state['notify_tile_captures']
        if 'notify_tile_deltas' in state:
            del state['notify_tile_deltas']
        if 'notify_city_found' in state:
            del state['notify_city_found']
        if 'notify_tile_discovered' in state:
            del state['notify_tile_discovered']
        if 'notify_tile_vision_changed' in state:
            del state['notify_tile_vision_changed']
        if 'notify_general_revealed' in state:
            del state['notify_general_revealed']
        if 'notify_player_captures' in state:
            del state['notify_player_captures']

        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.notify_tile_captures = []
        self.notify_tile_deltas = []
        self.notify_city_found = []
        self.notify_tile_discovered = []
        self.notify_tile_vision_changed = []
        self.notify_general_revealed = []
        self.notify_player_captures = []

    def get_all_tiles(self) -> typing.Generator[Tile, None, None]:
        for row in self.grid:
            for tile in row:
                yield tile

    def get_all_tiles_for_team_of_player(self, player: int) -> typing.Generator[Tile, None, None]:
        for p in self._teammates_by_player[player]:
            playerObj = self.players[p]

            for tile in playerObj.tiles:
                yield tile

    def get_all_tiles_for_team(self, teamId: int) -> typing.Generator[Tile, None, None]:
        for p in self._teammates_by_team[teamId]:
            playerObj = self.players[p]

            for tile in playerObj.tiles:
                yield tile

    def manhattan_dist(self, tileA: Tile, tileB: Tile) -> int:
        if self.modifiers_by_id[MODIFIER_TORUS]:
            xMin = min(abs(tileA.x - tileB.x), abs(tileA.x - tileB.x + self.cols), abs(tileB.x - tileA.x + self.cols))
            yMin = min(abs(tileA.y - tileB.y), abs(tileA.y - tileB.y + self.rows), abs(tileB.y - tileA.y + self.rows))

            return xMin + yMin
        return abs(tileA.x - tileB.x) + abs(tileA.y - tileB.y)

    def euclidDist(self, x: float, y: float, x2: float, y2: float) -> float:
        bestX = x
        bestY = y

        if self.modifiers_by_id[MODIFIER_TORUS]:
            stdX = abs(x - x2)
            best = stdX
            xPlus = abs(x - x2 + self.cols)
            if xPlus < best:
                best = xPlus
                bestX = x + self.cols

            xMinus = abs(x2 - x + self.cols)
            if xMinus < best:
                best = xMinus
                bestX = x - self.cols

            stdY = abs(y - y2)
            best = stdY
            yPlus = abs(y - y2 + self.cols)
            if yPlus < best:
                best = yPlus
                bestY = y + self.cols

            yMinus = abs(y2 - y + self.cols)
            if yMinus < best:
                best = yMinus
                bestY = y - self.cols

        if bestX == x2 and bestY == y2:
            return 0

        return pow(pow(abs(bestX - x2), 2) + pow(abs(bestY - y2), 2), 0.5)

    def euclidDistTile(self, a: Tile, b: Tile) -> float:
        return self.euclidDist(a.x, a.y, b.x, b.y)

    def GetTile(self, x, y) -> Tile | None:
        if x < 0 or x >= self.cols or y < 0 or y >= self.rows:
            return None
        return self.grid[y][x]

    def GetTileModifierSafe(self, x, y) -> Tile | None:
        if self.modifiers_by_id[MODIFIER_TORUS]:
            return self.GetTileTorus(x, y)

        return self.GetTile(x, y)

    def GetTileTorus(self, x, y) -> Tile:
        while x < 0:
            x += self.cols
        while x >= self.cols:
            x -= self.cols
        while y < 0:
            y += self.rows
        while y >= self.rows:
            y -= self.rows

        return self.grid[y][x]

    def _update_player_information(self, bypassDeltas: bool):
        cityCounts = [0 for i in range(len(self.players))]
        for player in self.players:
            if self.scores[player.index] is None:
                continue
            # print("player {}".format(player.index))
            player.scoreDelta = self.scores[player.index].total - player.score
            player.score = self.scores[player.index].total
            player.tileDelta = self.scores[player.index].tiles - player.tileCount
            player.unexplainedTileDelta = player.tileDelta
            player.tileCount = self.scores[player.index].tiles
            player.standingArmy = self.scores[player.index].total - self.scores[player.index].tiles

        last = self.scoreHistory[len(self.scoreHistory) - 1]
        earliest = last
        for i in range(len(self.scoreHistory) - 2, 0, -1):
            turn = self.turn - i
            scores = self.scoreHistory[i]
            # print("turn {}".format(turn))
            if earliest is None:
                earliest = scores
            if last is not None:
                for j, player in enumerate(self.players):
                    score = scores[j]
                    lastScore = last[j]
                    tileDelta = score.tiles - lastScore.tiles

                    # print("player {} delta {}".format(player.index, delta))
                    if abs(tileDelta) <= 2 and turn % 50 != 0:  # ignore army bonus turns and other player captures
                        delta = score.total - lastScore.total
                        if delta > 0:
                            cityCounts[j] = max(delta, cityCounts[j])
            last = scores
        self.remainingPlayers = 0
        for i, player in enumerate(self.players):
            if not player.dead:
                if earliest is not None:
                    player.delta25score = self.players[i].score - earliest[i].total
                    player.delta25tiles = self.players[i].tileCount - earliest[i].tiles
                if self.scores[i].dead:
                    # wait one turn upon receiving a 'dead' update to allow for 'capture' messages that are arriving late.
                    if not player.leftGame:
                        player.leftGame = True
                        player.leftGameTurn = self.turn

                        logbook.info(f'WARNING, setting dead player p{player.index} surrendered but hasnt left')
                    else:
                        logbook.info(f'WARNING, ok player left the game now, we can convert their stuff p{player.index} surrendered but hasnt left')
                        # don't immediately set 'dead' so that we keep attacking disconnected player
                        if self.scores[i].tiles == 0:
                            player.dead = True
                            if len(player.tiles) > 0:
                                for tile in player.tiles:
                                    if not tile.visible:
                                        tile.set_disconnected_neutral()

                        if self.generals[player.index] is not None:
                            logbook.info(f'WARNING, setting forfeited player p{player.index} general {self.generals[player.index]} = None')
                            self.generals[player.index] = None
                        if player.general is not None and player.general.isGeneral:
                            logbook.warning(f'WARNING, GENERAL WAS NOT RESET TO CITY ON DEAD PLAYER BY THE TIME WE WERE CALCULATING SCORES, THE FUCK? {player.general}')
                            player.general.isGeneral = False
                            player.general.isCity = True

                else:
                    self.remainingPlayers += 1

        if not bypassDeltas:
            self.calculate_player_deltas()

        if self.remainingPlayers > 2 and self.is_city_bonus_turn and not self.is_2v2:
            for i, player in enumerate(self.players):
                if not player.dead and player.index != self.player_index:
                    if player.cityCount < cityCounts[i]:
                        player.cityGainedTurn = self.turn
                    elif player.cityCount > cityCounts[i] > 0:
                        player.cityLostTurn = self.turn
                    player.cityCount = cityCounts[i]

    def handle_player_capture_text(self, text):
        capturer, capturee = text.split(" captured ")
        capturee = capturee[:-1]

        capturerIdx = self.get_id_from_username(capturer)
        captureeIdx = self.get_id_from_username(capturee)

        self.handle_player_capture(capturerIdx, captureeIdx)

    def handle_player_capture(self, capturerIdx: int, captureeIdx: int):
        if captureeIdx == self.player_index:
            logbook.info(
                f"\n\n    ~~~~~~~~~\nWE WERE CAPTURED BY {self.usernames[capturerIdx]}, IGNORING CAPTURE: {self.usernames[captureeIdx]} ({captureeIdx}) by {self.usernames[capturerIdx]} ({capturerIdx})\n    ~~~~~~~~~\n")
            return

        if self.player_index == capturerIdx or capturerIdx in self.teammates:
            logbook.info(
                f"\n\n    ~~~~~~~~~\nWE CAPTURED {captureeIdx}, NUKING UNDISCOVEREDS: {self.usernames[captureeIdx]} ({captureeIdx}) by {self.usernames[capturerIdx]} ({capturerIdx})\n    ~~~~~~~~~\n")
            for tile in self.get_all_tiles():
                if tile.player == captureeIdx and not tile.visible:
                    tile.reset_wrong_undiscovered_fog_guess()

        logbook.info(
            f"\n\n    ~~~~~~~~~\nPlayer captured: {self.usernames[captureeIdx]} ({captureeIdx}) by {self.usernames[capturerIdx]} ({capturerIdx})\n    ~~~~~~~~~\n")

        if captureeIdx < 0:
            raise AssertionError(f'what? Player captured was {captureeIdx}')

        for handler in self.notify_player_captures:
            handler(captureeIdx, capturerIdx)

        capturedGen = self.generals[captureeIdx]
        if capturedGen is None:
            capturedGen = self.players[captureeIdx].general
        if capturedGen is not None:
            capturedGen.isGeneral = False
            capturedGen.isCity = True
            for eventHandler in self.notify_city_found:
                eventHandler(capturedGen)
        self.generals[captureeIdx] = None

        capturingPlayer = self.players[capturerIdx]
        captureePlayer = self.players[captureeIdx]
        captureePlayer.capturedBy = capturerIdx
        logbook.info(f'increasing capturer p{capturerIdx} cities from {capturingPlayer.cityCount} by captured players {captureePlayer.cityCount} cityCount')
        capturingPlayer.cityCount += captureePlayer.cityCount
        for tile in self.get_all_tiles():
            if tile.player != captureeIdx:
                continue

            if not tile.discovered:
                # if tile.isCity:
                tile.reset_wrong_undiscovered_fog_guess()
                #
                # tile.army = 0
                # tile.tile = TILE_FOG
                # tile.player = -1
                # tile.isGeneral = False
                continue

            tile.discoveredAsNeutral = True
            # DONT use this, this sets deltas :s
            # tile.update(self, tile.tile, tile.army // 2, overridePlayer=capturerIdx)
            wasGeneral = tile.isGeneral
            tile.isGeneral = False
            tile.tile = capturerIdx
            tile.player = capturerIdx
            if wasGeneral:
                tile.isCity = True

                for eventHandler in self.notify_city_found:
                    eventHandler(tile)
            else:
                tile.army = tile.army - tile.army // 2

            for eventHandler in self.notify_tile_deltas:
                eventHandler(tile)

            if tile.isCity and tile not in capturingPlayer.cities:
                capturingPlayer.cities.append(tile)
                capturingPlayer.cityCount += 1

            for eventHandler in self.notify_tile_captures:
                eventHandler(tile)

    def get_id_from_username(self, username):
        for i, curName in enumerate(self.usernames):
            if username == curName:
                return i
        for i, curName in enumerate(self.usernames):
            if BotLogging.get_file_safe_username(username) == BotLogging.get_file_safe_username(curName):
                return i

        return -1

    def update_turn(self, turn: int):
        self.turn = turn
        self.clear_deltas()

    def update_scores(self, scores: typing.List[Score]):
        """ONLY call this when simulating the game"""
        self.scores = scores

    def get_team_stats_by_team_id(self, teamId: int) -> TeamStats:
        curStats = self._team_stats[teamId]

        if teamId == -1 and curStats is not None:
            curStats.turn = self.turn
            return curStats

        if curStats is None or curStats.turn != self.turn:
            for curTeamId in self.team_ids_by_player_index:
                tileCount = 0
                score = 0
                standingArmy = 0
                cities = 0
                fightingDiff = 0
                unexplainedTileDelta = 0
                teamPlayers = self._teammates_by_team[curTeamId]
                for pIdx in teamPlayers:
                    player = self.players[pIdx]

                    tileCount += player.tileCount
                    score += player.score
                    standingArmy += player.standingArmy
                    cities += player.cityCount
                    fightingDiff += player.actualScoreDelta - player.expectedScoreDelta
                    unexplainedTileDelta += player.unexplainedTileDelta

                teamStats = TeamStats(
                    tileCount=tileCount,
                    score=score,
                    standingArmy=standingArmy,
                    cityCount=cities,
                    fightingDiff=fightingDiff,
                    unexplainedTileDelta=unexplainedTileDelta,
                    teamId=curTeamId,
                    teamPlayers=teamPlayers,
                    livingPlayers=[p for p in teamPlayers if not self.players[p].dead],
                    turn=self.turn)

                self._team_stats[curTeamId] = teamStats
                if curTeamId == teamId:
                    curStats = teamStats

        return curStats

    def get_team_stats_lookup_by_team_id(self) -> typing.List[TeamStats]:
        if self._team_stats[0] is None or self._team_stats[0].turn != self.turn:
            self.get_team_stats_by_team_id(-1)  # force build
        return self._team_stats

    def get_team_stats(self, teamPlayer: int) -> TeamStats:
        if teamPlayer == -1:
            targetTeam = -1
        else:
            targetTeam = self.players[teamPlayer].team

        return self.get_team_stats_by_team_id(targetTeam)

    def is_player_friendly(self, player: int):
        return self.team_ids_by_player_index[player] == self.friendly_team

    def is_tile_friendly(self, tile: Tile) -> bool:
        if self.friendly_team == self.team_ids_by_player_index[tile._player]:
            return True
        return False

    def is_tile_enemy(self, tile: Tile) -> bool:
        if self.team_ids_by_player_index[tile._player] != self.friendly_team and tile._player >= 0:
            return True

        return False

    def is_tile_on_team_with(self, tile: Tile, player: int) -> bool:
        if self.team_ids_by_player_index[player] == self.team_ids_by_player_index[tile._player]:
            return True

        return False

    def is_tile_on_team(self, tile: Tile, team: int) -> bool:
        if team == self.team_ids_by_player_index[tile._player]:
            return True

        return False

    def is_player_on_team_with(self, player1: int, player2: int) -> bool:
        if self.team_ids_by_player_index[player1] == self.team_ids_by_player_index[player2]:
            return True

        return False

    def is_player_on_team(self, player: int, team: int) -> bool:
        if self.team_ids_by_player_index[player] == team:
            return True

        return False

    def iterate_tile_set(self, tileSet: TileSet) -> typing.Iterator[Tile]:
        if isinstance(tileSet, set):
            return iter(tileSet)

        return (self.tiles_by_index[i] for i, isInSet in enumerate(tileSet.raw) if isInSet)

    # Applies a tile update event from the server. Call this method directly to pretend a server update happend to a tile in tests. Changes player tile ownership, or mountain to city, etc, and fires events
    def update_visible_tile(
            self,
            x: int,
            y: int,
            tile_type: int,
            tile_army: int,
            is_city: bool = False,
            is_general: bool = False):
        """
        Call this AFTER calling map.update_turn.
        ONLY call this ONCE per turn per tile, or the first deltas will be replaced by the final delta.
        THEN once all tile updates are queued, call map.update() to process all the updates into tile movements.

        @param x:
        @param y:
        @param tile_type:
        @param tile_army:
        @param is_city:
        @param is_general:
        @return:
        """
        curTile: Tile = self.grid[y][x]
        wasCity = curTile.isCity
        wasVisible = curTile.visible
        wasDiscovered = curTile.discovered
        wasGeneral = curTile.isGeneral
        if curTile.isCity and tile_type >= TILE_EMPTY and not is_city:
            curTile.isCity = False

        # does the ACTUAL tile update
        maybeMoved = curTile.update(self, tile_type, tile_army, is_city, is_general)
        
        if tile_type == TILE_OBSERVATORY:
            self.observatories.add(curTile)
        if tile_type == TILE_LOOKOUT:
            self.lookouts.add(curTile)

        if not is_general and tile_type >= TILE_EMPTY and curTile.isGeneral:
            curTile.isGeneral = False

        self.army_moved_grid[y][x] = maybeMoved
        if curTile.delta.oldOwner != curTile.delta.newOwner:
            curTile.turn_captured = self.turn
            for eventHandler in self.notify_tile_captures:
                eventHandler(curTile)
            for eventHandler in self.notify_tile_deltas:
                eventHandler(curTile)
        if curTile.delta.armyDelta != 0:
            for eventHandler in self.notify_tile_deltas:
                eventHandler(curTile)
        if wasCity != curTile.isCity:
            for eventHandler in self.notify_city_found:
                eventHandler(curTile)
        if wasDiscovered != curTile.discovered:
            for eventHandler in self.notify_tile_discovered:
                eventHandler(curTile)
        if wasVisible != curTile.visible:
            for eventHandler in self.notify_tile_vision_changed:
                eventHandler(curTile)
        if wasGeneral != curTile.isGeneral:
            for eventHandler in self.notify_general_revealed:
                eventHandler(curTile)
            if curTile.isGeneral and curTile.visible:
                logbook.info(f' SET map.generals[{curTile.player}] = {curTile} IN map.py (was {self.generals[curTile.player]})')
                self.generals[curTile.player] = curTile
            elif curTile.visible:
                if curTile.delta.oldOwner != -1 and self.generals[curTile.delta.oldOwner] == curTile:
                    logbook.info(f' SET oldOwner map.generals[{curTile.delta.oldOwner}] = NONE IN map.py (was {self.generals[curTile.delta.oldOwner]})')
                    self.generals[curTile.delta.oldOwner] = None
            else:
                logbook.error(f' WTF is going on with generals?? tile {curTile}  delta {curTile.delta}  isGeneral{curTile.isGeneral} wasGeneral{wasGeneral}')
                logbook.error(f'    generals {str(self.generals)}')

                # curTile.isGeneral = False
                # for i, maybeNotGen in list(enumerate(self.generals)):
                #     if maybeNotGen is not None and maybeNotGen.player != i:
                #         maybeNotGen.isCity = True
                #         maybeNotGen.isGeneral = False
                #         self.generals[i] = None

    def update(self, bypassDeltas: bool = False):
        """
        Expects _applyUpdateDiff to have been run to update the hidden _grid info first.
        Expects update_turn() to have been called with the new turn already.
        Expects update_visible_tile to have been called already for all tiles with updates.
        Expects scores to have been recreated from latest data.

        @param bypassDeltas: If passes, fog-city-and-army-increments will not be applied this turn, and tile-movement deltas will not be tracked.
        """

        for player in self.players:
            player.lastCityCount = player.cityCount
            player.knownScoreDelta = 0
            # player.last_fighting_with_player = player.fighting_with_player
            # player.fighting_with_player = -1

        if self.complete and not self.result and self.remainingPlayers > 2:  # Game Over - Ignore Empty Board Updates in FFA
            return self

        for curTile in self.get_all_tiles():
            if curTile.isCity and curTile.delta.oldOwner != curTile.delta.newOwner and not curTile.delta.gainedSight:
                oldOwner = curTile.delta.oldOwner
                newOwner = curTile.player
                # if self.remainingPlayers > 2 or not self.is_city_bonus_turn:
                #     curTile.
                if oldOwner != -1:
                    logbook.info(f'decrementing p{oldOwner}s cities due to {str(curTile)} flipping to p{newOwner}')
                    self.players[oldOwner].cityCount -= 1

                self.players[newOwner].cityCount += 1

            if curTile.delta.gainedSight:
                self.visible_tiles.add(curTile)
            elif curTile.delta.lostSight:
                self.visible_tiles.discard(curTile)

        for i in range(len(self.scoreHistory) - 1, 0, -1):
            self.scoreHistory[i] = self.scoreHistory[i - 1]
        self.scoreHistory[0] = self.scores

        self._update_player_information(bypassDeltas=bypassDeltas)

        for player in self.players:
            if player is not None:
                player.cities = []
                player.tiles = []
                player.visibleStandingArmy = 0

        # right now all tile deltas are completely raw, as applied by the raw server update, with the exception of lost-vision-fog.

        for x in range(self.cols):
            for y in range(self.rows):
                curTile = self.grid[y][x]

                if curTile.player >= 0:
                    self.players[curTile.player].tiles.append(curTile)
                    if curTile.visible:
                        self.players[curTile.player].visibleStandingArmy += curTile.army - 1

                if curTile.isCity and curTile.player != -1:
                    self.players[curTile.player].cities.append(curTile)

        if not bypassDeltas:
            self.detect_movement_and_populate_unexplained_diffs()

        if not bypassDeltas:
            for x in range(self.cols):
                for y in range(self.rows):
                    curTile = self.grid[y][x]
                    if (not curTile.visible and (
                            curTile.isCity or curTile.isGeneral) and curTile.player >= 0 and self.is_city_bonus_turn):
                        curTile.army += 1
                    if not curTile.visible and curTile.player >= 0 and self.is_army_bonus_turn:
                        curTile.army += 1

        self.update_reachable()

        # we know our players city count + his general because we can see all our own cities
        self.players[self.player_index].cityCount = len(self.players[self.player_index].cities) + 1
        for teammate in self.teammates:
            self.players[teammate].cityCount = len(self.players[teammate].cities) + 1

        return self

    def init_grid_movable(self):
        for x in range(self.cols):
            for y in range(self.rows):
                tile = self.grid[y][x]
                if len(tile.adjacents) != 0:
                    continue

                movableTile = self.GetTileModifierSafe(x - 1, y)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                movableTile = self.GetTileModifierSafe(x + 1, y)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                movableTile = self.GetTileModifierSafe(x, y - 1)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                movableTile = self.GetTileModifierSafe(x, y + 1)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                adjTile = self.GetTileModifierSafe(x - 1, y - 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)
                adjTile = self.GetTileModifierSafe(x + 1, y - 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)
                adjTile = self.GetTileModifierSafe(x - 1, y + 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)
                adjTile = self.GetTileModifierSafe(x + 1, y + 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)

                if tile.isGeneral:
                    if tile.player == -1:
                        raise AssertionError(f'Cant have neutral generals idiot')

                    self.generals[tile.player] = tile

                if not MapBase.DO_NOT_RANDOMIZE:
                    random.shuffle(tile.adjacents)
                    random.shuffle(tile.movable)

        self.update_reachable()

    def update_reachable(self):
        pathableTiles = set()
        reachableTiles = set()
        visibleTiles = set()

        queue = deque()

        for gen in self.generals:
            if gen is not None:
                queue.append(gen)
                self.players[gen.player].general = gen

        while queue:
            tile = queue.popleft()
            if tile.visible:
                visibleTiles.add(tile)
            isNeutCity = tile.isCity and tile.isNeutral
            tileIsPathable = not tile.isNotPathable
            if tile not in pathableTiles and tileIsPathable and not isNeutCity:
                pathableTiles.add(tile)
                for movable in tile.movable:
                    queue.append(movable)
                    reachableTiles.add(movable)

        self.pathable_tiles = pathableTiles
        self.reachable_tiles = reachableTiles
        self.visible_tiles = visibleTiles
        self.unreachable_tiles = {t for t in self.get_all_tiles() if t not in reachableTiles}
        self.unpathable_tiles = {t for t in self.get_all_tiles() if t not in pathableTiles}
        self.non_visible_tiles = {t for t in self.get_all_tiles() if t not in visibleTiles}

    def clear_deltas_and_score_history(self):
        self.scoreHistory = [None for i in range(50)]
        self.scoreHistory[0] = list(self.scores)
        self.clear_deltas()

    def clear_deltas(self):
        for tile in self.get_all_tiles():
            tile.delta = TileDelta()
            # Make the deltas look normal, otherwise loading a map mid-game looks to the bot like these tiles all got attacked by something on army bonus turns etc.
            # if self.is_army_bonus_turn and tile.player >= 0:
            #     tile.delta.armyDelta += 1
            # if self.is_city_bonus_turn and tile.player >= 0 and (tile.isGeneral or tile.isCity):
            #     tile.delta.armyDelta += 1
        self.army_moved_grid = [[False for x in range(self.cols)] for y in range(self.rows)]
        self.army_emergences: typing.Dict[Tile, int] = {}

    @staticmethod
    def player_had_priority_over_other(player: int, otherPlayer: int, turn: int):
        """Whether the player HAD priority on the current turns move that they sent last turn"""
        return (turn & 1 == 0) == (player > otherPlayer)

    @staticmethod
    def player_has_priority_over_other(player: int, otherPlayer: int, turn: int):
        """Whether the player WILL HAVE priority on the move they are about to make on current turn"""
        return (turn & 1 == 0) != (player > otherPlayer)

    def convert_tile_to_mountain(self, tile: Tile):
        self.pathable_tiles.discard(tile)
        if tile.isCity:
            for player in self.players:
                if tile in player.cities:
                    player.cities.remove(tile)
        tile.tile = TILE_MOUNTAIN
        tile.isCity = False
        tile.army = 0
        tile.isGeneral = False
        tile.player = -1
        tile.isMountain = True

    def set_tile_probably_moved(self, toTile: Tile, fromTile: Tile, fullFromDiffCovered = True, fullToDiffCovered = True, byPlayer = -1) -> bool:
        """
        Sets the tiles delta.armyMoveHeres appropriately based on the *DiffCovered params.
        Updates the delta.fromTile and delta.toTile.
        If either tile is not visible, corrects the armyDelta, unexplainedDelta, newOwner, etc in the delta.

        @param toTile:
        @param fromTile:
        @param fullFromDiffCovered: Whether you determined the movement accounts for the entirety of the from-tiles army delta diff, excluding it from any future calculations this turn.
        @param fullToDiffCovered: Whether you determined the movement accounts for the entirety of the to-tiles army delta diff, excluding it from any future calculations this turn.
        @param byPlayer: if not provided will be determined based on fromTile.delta.oldOwner. Provide this for moves from fog where oldOwner might be incorrect.
        @return:
        """
        if byPlayer == -1:
            byPlayer = fromTile.delta.oldOwner

        isMoveHalf = False

        logbook.info(f'MOVE {repr(fromTile)} -> {repr(toTile)} (fullFromDiffCovered {fullFromDiffCovered}, fullToDiffCovered {fullToDiffCovered})')
        self.army_moved_grid[fromTile.y][fromTile.x] = self.army_moved_grid[fromTile.y][fromTile.x] and not fullFromDiffCovered
        # if not self.USE_OLD_MOVEMENT_DETECTION:
        self._update_moved_here(fromTile, fromTile.delta.armyMovedHere and not fullFromDiffCovered)

        expectedDelta = self._get_expected_delta_amount_toward(fromTile, toTile)

        # if not fromTile.was_visible_last_turn():  # 8485 failed (with other changes)
        # if not fromTile.visible and not fromTile.was_visible_last_turn(): # 8129 failed
        # if not fromTile.visible and fromTile.delta.oldOwner != self.player_index: # 5135 failed
        if not fromTile.visible:  #5095 failed (with other current changes), this is what it originally was
            if expectedDelta != toTile.delta.unexplainedDelta and toTile.visible and fromTile.delta.oldOwner != self.player_index:
                halfDelta = self._get_expected_delta_amount_toward(fromTile, toTile, moveHalf=True)
                if abs(toTile.delta.unexplainedDelta - expectedDelta) > abs(toTile.delta.unexplainedDelta - halfDelta):
                    expectedDelta = halfDelta
                    isMoveHalf = True

            fromDelta = expectedDelta

            fromTile.army += fromDelta
            fromTile.delta.armyDelta = fromDelta

            isByPlayerFriendly = self.is_player_friendly(byPlayer)

            if fromTile.player != byPlayer and byPlayer >= 0 and not isByPlayerFriendly:
                if fromTile.player >= 0:
                    if fromTile.isCity:
                        self.players[fromTile.player].cities.remove(fromTile)
                    self.players[fromTile.player].tiles.remove(fromTile)
                fromTile.player = byPlayer
                byPlayerObj = self.players[byPlayer]
                byPlayerObj.tiles.append(fromTile)
                if fromTile.army > 0 and not self.is_player_friendly(fromTile.delta.oldOwner):
                    msg = f'fromTile was neutral/otherPlayer {fromTile.delta.oldOwner} with positive army {fromTile.army} in the fog. From->To: {repr(fromTile)} -> {repr(toTile)}'
                    if ENABLE_DEBUG_ASSERTS:
                        raise AssertionError(msg)
                    else:
                        logbook.error(msg)
                        fromTile.army = 0 - fromTile.army
                if fromTile.isUndiscoveredObstacle:
                    fromTile.isCity = True
                    fromTile.army = 1
                    fromTile.isMountain = False
                    if not fromTile.discovered:
                        fromTile.discovered = fullFromDiffCovered
                        fromTile.delta.discovered = fullFromDiffCovered
                    fromTile.isTempFogPrediction = not fullFromDiffCovered

                if fromTile.isCity and fromTile not in byPlayerObj.cities:
                    byPlayerObj.cities.append(fromTile)
                    # if self.is_army_bonus_turn:
                    #     fromTile.army += 1
                    # if self.is_city_bonus_turn:
                    #     fromTile.army += 1
            if not isByPlayerFriendly:
                self.set_fog_moved_from_army_incremented(fromTile, byPlayer, expectedDelta)
        # else:
        #     halfDiff = fromTile.delta.oldArmy // 2
        #     if (expectedDelta == 0 - halfDiff or expectedDelta == halfDiff) and expectedDelta == 0 - fromTile.delta.unexplainedDelta and expectedDelta != 0:
        #         isMoveHalf = True

        # only say the army is completely covered if the confidence was high, otherwise we can have two armies move here from diff players
        self.army_moved_grid[toTile.y][toTile.x] = self.army_moved_grid[toTile.y][toTile.x] and not fullToDiffCovered
        # if not self.USE_OLD_MOVEMENT_DETECTION:
        self._update_moved_here(toTile, toTile.delta.armyMovedHere and not fullToDiffCovered)

        if not toTile.visible:
            toTile.army = toTile.army + expectedDelta
            toTile.delta.armyDelta += expectedDelta
            if toTile.army < 0:
                toTile.army = 0 - toTile.army
                toTile.player = byPlayer
                # toTile.delta.newOwner = byPlayer
                toTile.delta.newOwner = byPlayer
            if toTile.isUndiscoveredObstacle:
                toTile.isCity = True
                toTile.isTempFogPrediction = not fullFromDiffCovered
                # toTile.delta.unexplainedDelta = 0

        # prefer leaving enemy move froms, as they're harder for armytracker to track since it doesn't have the last move spelled out like it does for friendly moves.
        if toTile.delta.fromTile is None or toTile.delta.fromTile.delta.oldOwner != self.player_index:
            toTile.delta.fromTile = fromTile

        if fullFromDiffCovered:
            if fromTile.delta.gainedSight:
                if fromTile.delta.oldOwner == fromTile.player:
                    self._update_unexplained_delta(fromTile, fromTile.delta.unexplainedDelta - toTile.delta.unexplainedDelta)
                else:
                    self._update_unexplained_delta(fromTile, fromTile.delta.unexplainedDelta - toTile.delta.unexplainedDelta)
                self.set_fog_emergence(fromTile, armyEmerged=fromTile.delta.unexplainedDelta, byPlayer=fromTile.player)
            else:
                self._update_unexplained_delta(fromTile, 0)

        if fullToDiffCovered:
            self._update_unexplained_delta(toTile, 0)
        else:
            self._update_unexplained_delta(toTile, toTile.delta.unexplainedDelta - expectedDelta)

            if toTile.delta.unexplainedDelta == 0:
                self._update_moved_here(toTile, False)

        fromTile.delta.toTile = toTile
        logbook.info(f'  done: {repr(fromTile)} -> {repr(toTile)}{"z" if isMoveHalf else ""}')

        return isMoveHalf

    def set_tile_moved(self, toTile: Tile, fromTile: Tile, fullFromDiffCovered = True, fullToDiffCovered = True, byPlayer=-1):
        """
        Only call this when you KNOW the tile moved to the dest location.

        Sets the tiles delta.armyMoveHeres appropriately based on the *DiffCovered params.
        Updates the delta.fromTile and delta.toTile.
        If either tile is not visible, corrects the armyDelta, unexplainedDelta, newOwner, etc in the delta.
        Sets the players last move.

        @param toTile:
        @param fromTile:
        @param fullFromDiffCovered: Whether you determined the movement accounts for the entirety of the from-tiles army delta diff, excluding it from any future calculations this turn.
        @param fullToDiffCovered: Whether you determined the movement accounts for the entirety of the to-tiles army delta diff, excluding it from any future calculations this turn.
        @param byPlayer: if not provided will be determined based on fromTile.delta.oldOwner. Provide this for moves from fog where oldOwner might be incorrect.
        @return:
        """

        if byPlayer == -1:
            byPlayer = fromTile.delta.oldOwner
        if byPlayer == -1:
            raise AssertionError(f'must supply a player for moves from fog with unknown ownership when setting definitely-moved. fromTile was neutral. fromTile {repr(fromTile)} -> toTile {repr(toTile)}')

        isMoveHalf = self.set_tile_probably_moved(
            toTile,
            fromTile,
            fullFromDiffCovered,
            fullToDiffCovered,
            byPlayer=byPlayer,
        )

        if byPlayer >= 0:
            movingPlayer = self.players[byPlayer]

            if toTile.delta.oldOwner != toTile.player and (toTile.player == byPlayer or not toTile.visible):
                movingPlayer.unexplainedTileDelta -= 1
                logbook.info(f'   captured a tile, dropping the player tileDelta from unexplained for capturer p{movingPlayer.index} ({movingPlayer.unexplainedTileDelta + 1}->{movingPlayer.unexplainedTileDelta}).')
                if toTile.delta.oldOwner != -1:
                    attackedPlayer = self.players[toTile.delta.oldOwner]
                    if movingPlayer.team != attackedPlayer.team:
                        armyAmt = fromTile.delta.armyDelta
                        armyAmt = max(0 - toTile.delta.oldArmy, armyAmt)
                        movingPlayer.knownScoreDelta += armyAmt
                        attackedPlayer.knownScoreDelta += armyAmt

                    attackedPlayer.unexplainedTileDelta += 1
                    logbook.info(f'   captured a tile, dropping the player tileDelta from unexplained for capturee p{attackedPlayer.index} ({attackedPlayer.unexplainedTileDelta - 1}->{attackedPlayer.unexplainedTileDelta}).')

            movingPlayer.last_move = (fromTile, toTile, isMoveHalf)

            # if not self.USE_OLD_MOVEMENT_DETECTION and not fromTile.visible:
            #     movementAmount = fromTile.delta.oldArmy - 1
            #     if movementAmount >
            #     fromTile.army = self.get_fog_moved_from_army_incremented(fromTile)
            #     if not toTile.visible:

    def _is_partial_army_movement_delta_match(self, source: Tile, dest: Tile):
        if source.delta.imperfectArmyDelta:
            if dest.delta.unexplainedDelta != 0:
                return True
            return False
        if dest.delta.imperfectArmyDelta:
            if source.delta.unexplainedDelta != 0:
                return True
            return False

        if self._move_would_violate_known_player_deltas(source, dest):
            return False

        deltaToDest = self._get_expected_delta_amount_toward(source, dest)
        if deltaToDest == dest.delta.unexplainedDelta:
            return True
        elif dest.delta.unexplainedDelta != 0 and deltaToDest != 0:
            return True
        return False

    def _is_exact_army_movement_delta_dest_match(self, source: Tile, dest: Tile):
        if source.delta.imperfectArmyDelta:
            return self._is_exact_lost_source_vision_movement_delta_match(source, dest)
        if dest.delta.imperfectArmyDelta:
            return self._is_exact_lost_dest_vision_movement_delta_match(source, dest)
        if self._move_would_violate_known_player_deltas(source, dest):
            return False

        deltaToDest = self._get_expected_delta_amount_toward(source, dest)
        if deltaToDest != dest.delta.unexplainedDelta:
            return False

        return True

    def _is_exact_army_movement_delta_source_match(self, source: Tile, dest: Tile):
        if source.delta.imperfectArmyDelta:
            return self._is_exact_lost_source_vision_movement_delta_match(source, dest)
        if dest.delta.imperfectArmyDelta:
            return self._is_exact_lost_dest_vision_movement_delta_match(source, dest)
        if self._move_would_violate_known_player_deltas(source, dest):
            return False

        if not source.was_visible_last_turn() or not source.visible:
            return False

        deltaFromSource = self._get_expected_delta_amount_from(source, dest)
        if deltaFromSource != source.delta.unexplainedDelta:
            return False

        return True

    def _is_exact_army_movement_delta_all_match(self, source: Tile, dest: Tile):
        if not self._is_exact_army_movement_delta_dest_match(source, dest):
            return False

        if source.was_visible_last_turn() and source.visible:
            deltaFromSource = self._get_expected_delta_amount_from(source, dest)
            if deltaFromSource != source.delta.unexplainedDelta:
                return False

        return True

    def _is_exact_lost_source_vision_movement_delta_match(self, source: Tile, dest: Tile):
        """Detects if a move from a tile that we just lost vision of would have resulted in the exact dest delta."""
        if not source.delta.lostSight:
            return False
        if self._move_would_violate_known_player_deltas(source, dest):
            return False

        deltaToDest = self._get_expected_delta_amount_toward(source, dest)
        if deltaToDest == dest.delta.unexplainedDelta:
            return True

        deltaToDest = self._get_expected_delta_amount_toward(source, dest, moveHalf=True)
        if deltaToDest == dest.delta.unexplainedDelta:
            return True

        return False

    def _is_exact_lost_dest_vision_movement_delta_match(self, source: Tile, dest: Tile):
        """Detects if a move to a tile that we just lost vision of would have resulted in the exact dest delta."""
        if not dest.delta.lostSight:
            return False
        if self._move_would_violate_known_player_deltas(source, dest):
            return False

        deltaToDest = self._get_expected_delta_amount_toward(source, dest)
        if deltaToDest == dest.delta.unexplainedDelta:
            return True

        if not source.visible:
            deltaToDest = self._get_expected_delta_amount_toward(source, dest, moveHalf=True)
            if deltaToDest == dest.delta.unexplainedDelta:
                return True

        return False

    def _get_expected_delta_amount_toward(self, source: Tile, dest: Tile, moveHalf: bool = False) -> int:
        sameOwnerMove = source.delta.oldOwner == dest.delta.oldOwner and source.delta.oldOwner != -1  # and (dest.player == source.delta.oldOwner or dest.player != self.player_index)
        attackedFlippedTile = dest.delta.oldOwner != dest.player and source.delta.oldOwner != dest.player and dest.visible
        teamMateMove = source.delta.oldOwner != dest.delta.oldOwner and self.team_ids_by_player_index[source.delta.oldOwner] == self.team_ids_by_player_index[dest.delta.oldOwner]
        expectedDelta = source.delta.unexplainedDelta
        if not source.visible:
            if not source.delta.lostSight:
                expectedDelta = dest.delta.unexplainedDelta

                # if not dest.visible:
                #     expectedDelta = source.delta.oldArmy - 1
                #     # OK so this ^ was wrong, all tests pass with it commented out, should have been:
                #     expectedDelta = 0 - (source.delta.oldArmy - 1)

            else:
                expectedDelta = 0 - (source.delta.oldArmy - 1)
                if moveHalf:
                    expectedDelta = 0 - source.delta.oldArmy // 2
        # END TODO REMOVE ME

        bypassNeutFogSource = False
        if not source.visible:
            # how the fuck does this make sense
            sourceNeut = bypassNeutFogSource = source.player == -1
            # TODO does this need to get fancier with potential movers vs the dest owner...?
            # TODO try commenting this out...?
            sameOwnerMove = (sameOwnerMove or (sourceNeut and not source.delta.lostSight)) and dest.delta.oldOwner != -1
        elif moveHalf:
            raise AssertionError(f'cannot provide moveHalf directive for visible tile {str(source)}, visible tiles exclusively use tile deltas.')
        if sameOwnerMove or (attackedFlippedTile and not bypassNeutFogSource):
            return 0 - expectedDelta
        if teamMateMove:
            if not dest.isGeneral:
                if dest.delta.fromTile is not None and dest.delta.fromTile.delta.oldOwner == dest.player and source.player != dest.player:
                    # then ally moved at this tile with priority with us, and the other one won. Delta is purely 0-sourceDelta in that case.
                    return 0-expectedDelta
                # otherwise, the ally flipped the tile in their favor
                return 0 - (2 * dest.delta.oldArmy - expectedDelta)
            else:
                return 0 - expectedDelta

        return expectedDelta

    def _apply_last_player_move(self, last_player_index_submitted_move: typing.Tuple[Tile, Tile, bool]) -> typing.Tuple[Tile, Tile, bool] | None:
        """
        Returns None if the player move was determined to have been dropped or completely killed with priority at the source tile before executing.
        Updates the source and dest tiles unexplained deltas, if both are zero then the move should have executed cleanly with no interferences.

        @param last_player_index_submitted_move:
        @return: None if move wasn't performed, else the move.
        """
        source: Tile
        dest: Tile
        move_half: bool

        source, dest, move_half = last_player_index_submitted_move

        # source.delta.imperfectArmyDelta = False
        # dest.delta.imperfectArmyDelta = False
        oldSourceMovedHere = source.delta.armyMovedHere
        oldDestMovedHere = dest.delta.armyMovedHere
        self._update_moved_here(source, False)
        self._update_moved_here(dest, False)

        logbook.info(
            f"    tile (last_player_index_submitted_move) probably moved from {str(source)} to {str(dest)} with move_half {move_half}")
        # don't use the delta getter function because that operates off of the observed delta instead of what
        #  we know we tried to do, which is how we calculate second and third party interference.
        expectedDestDelta = source.delta.oldArmy - 1
        if move_half:
            expectedDestDelta = source.delta.oldArmy // 2

        expectedSourceDelta = 0 - expectedDestDelta  # these should always match if no other army interferes.

        if dest.delta.oldOwner != self.player_index and dest.delta.oldOwner not in self.teammates:
            expectedDestDelta = 0 - expectedDestDelta
        elif dest.delta.oldOwner in self.teammates and not dest.isGeneral:
            expectedDestDelta = 0 - (dest.delta.oldArmy * 2 + expectedDestDelta)

        sourceWouldHaveCappedDest = dest.delta.oldOwner == self.player_index or (dest.delta.oldOwner in self.teammates and not dest.isGeneral) or dest.delta.oldArmy + expectedSourceDelta < 0

        if source.delta.unexplainedDelta == 0 and source.visible:
            if dest.delta.unexplainedDelta == 0 and dest.visible:
                logbook.error(
                    f'    map determined player DEFINITELY dropped move {str(last_player_index_submitted_move)}. Setting last move to none...')
                self.last_player_index_submitted_move = None
                self._update_moved_here(source, oldSourceMovedHere)
                self._update_moved_here(dest, oldDestMovedHere)
                return None
            else:
                logbook.error(
                    f'    map determined player PROBABLY dropped move {str(last_player_index_submitted_move)}, but the dest DID have an army delta, double check on this... Continuing in case this is 2v2 BS or something.')

        # ok, then probably we didn't drop a move.

        actualSrcDelta = source.delta.unexplainedDelta
        if source.delta.lostSight:
            actualSrcDelta = -1 - source.delta.oldArmy

        actualDestDelta = dest.delta.unexplainedDelta

        srcUnexpectedDelta = actualSrcDelta - expectedSourceDelta
        sourceDeltaMismatch = srcUnexpectedDelta != 0

        destUnexpectedDelta = actualDestDelta - expectedDestDelta
        # necessary for test_should_not_dupe_army_to_the_side_on_collision
        if dest.delta.oldOwner != dest.player and dest.player != self.player_index and dest.delta.oldOwner != self.player_index:
            # detect if collided on tile that wasn't ours, and we didnt win
            destUnexpectedDelta = (0 - actualDestDelta) - expectedDestDelta
        # elif dest.delta.oldOwner != dest.player and dest.player == self.player_index:
        #     # detect if collided on tile that wasn't ours, and we DID win.
        #     destUnexpectedDelta = 0 - destUnexpectedDelta

        hasDestDeltaMismatch = destUnexpectedDelta != 0

        sourceDefinitelyKilledWithPriority = not source.visible and not dest.visible and sourceWouldHaveCappedDest

        # check for mutual attack
        if (
            sourceDeltaMismatch
            and destUnexpectedDelta == srcUnexpectedDelta
            and dest.delta.oldOwner != self.player_index
            and dest.delta.oldOwner not in self.teammates
            and dest.delta.oldOwner != -1
        ):
            logbook.info(f'MOVE {str(last_player_index_submitted_move)} was mutual attack?')
            self.set_tile_moved(toTile=source, fromTile=dest, fullFromDiffCovered=True, fullToDiffCovered=True, byPlayer=dest.delta.oldOwner)
            if actualDestDelta <= expectedSourceDelta:
                logbook.info(f'   Mutual attack appears to have fully cancelled out our move, returning no move from us.')
                self.last_player_index_submitted_move = None
                self._update_moved_here(source, source.delta.unexplainedDelta != 0)
                self._update_moved_here(dest, dest.delta.unexplainedDelta != 0)
                return None

        sourceHasEnPriorityDeltasNearby = False
        for tile in source.movable:
            if (
                    tile != dest
                    and (tile.delta.unexplainedDelta != 0 or tile.delta.lostSight)
                    and tile.delta.oldOwner != self.player_index
            ):
                if MapBase.player_had_priority_over_other(tile.delta.oldOwner, self.player_index, self.turn):
                    sourceHasEnPriorityDeltasNearby = True

        destHasEnDeltasNearby = False
        for tile in dest.movable:
            if (
                    tile != source
                    and ((tile.delta.unexplainedDelta != 0 and not tile.delta.gainedSight) or not tile.visible)
                    #and (tile.delta.oldOwner != self.player_index or tile.delta.newOwner != self.player_index)
            ):
                destHasEnDeltasNearby = True

        if not sourceHasEnPriorityDeltasNearby and not destHasEnDeltasNearby:
            for tile in dest.movable:
                if (
                        tile != source
                        and tile.delta.gainedSight
                        and tile.player != -1  # does not fail any new tests on its own.
                        # and (tile.delta.gainedSight or (tile.delta.lostSight and self.is_player_friendly(tile.delta.oldOwner)))
                        # and (tile.delta.oldOwner != self.player_index or tile.delta.newOwner != self.player_index)
                ):
                    destHasEnDeltasNearby = True

        sourceWasCaptured = False
        sourceWasAttackedWithPriority = False
        # if sourceDeltaMismatch or source.player != self.player_index or (actualDestDelta == 0 and sourceHasEnPriorityDeltasNearby):
        if sourceDeltaMismatch or source.player != self.player_index or (hasDestDeltaMismatch and sourceHasEnPriorityDeltasNearby) or sourceDefinitelyKilledWithPriority:
            if sourceHasEnPriorityDeltasNearby:
                sourceWasAttackedWithPriority = True
                if source.player != self.player_index or not source.visible:
                    armyMovedToDest = True
                    logbook.info(
                        f'MOVE {str(last_player_index_submitted_move)} seems to have been captured with priority. Nuking our last move.')
                    if dest.delta.unexplainedDelta != 0:
                        logbook.error(
                            f'  ^ {str(last_player_index_submitted_move)} IS QUESTIONABLE THOUGH BECAUSE DEST DID HAVE AN UNEXPLAINED DIFF. NUKING ANYWAY.')
                    else:
                        armyMovedToDest = False

                    self._update_moved_here(source, True)
                    self._update_moved_here(dest, armyMovedToDest)
                    self.last_player_index_submitted_move = None
                    return None
                else:
                    if actualDestDelta == 0:
                        logbook.info(
                            f'MOVE {str(last_player_index_submitted_move)} seems to have been attacked with priority down to where we dont capture anything. Nuking our last move.')
                        self._update_moved_here(source, True)
                        self.last_player_index_submitted_move = None
                        return None

            elif source.player != self.player_index:
                if not source.visible and not dest.visible and dest.delta.oldArmy + expectedDestDelta >= 0:
                    # then we assume the army reached it with priority but since we didn't cap the tile we just don't see that it happened.
                    logbook.info(
                        f'MOVE {str(last_player_index_submitted_move)} was capped WITHOUT priority. Our move probably still executed though, as it would not have captured the dest tile.')

                    self._update_moved_here(source, True)
                    self._update_moved_here(dest, False)
                    return source, dest, move_half
                else:
                    logbook.info(
                        f'MOVE {str(last_player_index_submitted_move)} was capped WITHOUT priority..? Adding unexplained diff {srcUnexpectedDelta} based on actualSrcDelta {actualSrcDelta} - expectedSourceDelta {expectedSourceDelta}. Continuing with dest diff calc')
                    # self.unaccounted_tile_diffs[source] = srcUnexpectedDelta  # negative number

                    if not source.visible:
                        # we lost sight of our own moving tile
                        # TODO this might be wrong? idk
                        self._update_unexplained_delta(source, actualSrcDelta)
                        # this should be right
                        if dest.visible:
                            self._update_unexplained_delta(source, actualDestDelta - expectedDestDelta)
                    else:
                        self._update_unexplained_delta(source, actualSrcDelta)
                        if dest.visible:
                            self._update_unexplained_delta(source, srcUnexpectedDelta - actualDestDelta + expectedDestDelta)

                    self._update_moved_here(source, True)
                    # TODO this is wrong...? Need to account for the amount of dest delta we think made it...?
            else:
                # we can get here if the source tile was attacked with priority but not for full damage, OR if it was attacked without priority for non full damage...
                destArmyInterferedToo = False
                if not hasDestDeltaMismatch:
                    # then we almost certainly didn't have source attacked with priority.
                    logbook.warn(
                        f'MOVE {str(last_player_index_submitted_move)} ? src attacked for srcUnexpectedDelta {srcUnexpectedDelta} WITHOUT priority based on actualSrcDelta {actualSrcDelta} vs expectedSourceDelta {expectedSourceDelta}')
                elif destHasEnDeltasNearby:
                    armyMadeItToDest = dest.delta.unexplainedDelta
                    srcUnexpectedDelta = expectedDestDelta - armyMadeItToDest
                    if source.army == 0:
                        srcUnexpectedDelta -= 1  # enemy can attack us down to 0 without flipping the tile, special case this

                    logbook.warn(
                        f'MOVE {str(last_player_index_submitted_move)} ? src attacked for srcUnexpectedDelta {srcUnexpectedDelta} based on destDelta {dest.delta.unexplainedDelta} vs expectedDestDelta {expectedDestDelta}')
                else:
                    destArmyInterferedToo = True
                    # TODO what to do here?
                    logbook.warn(
                        f'???MOVE {str(last_player_index_submitted_move)} ? player had priority but we still had a dest delta as well as source delta...?')
                    self._update_moved_here(dest, True)

                self._update_unexplained_delta(source, srcUnexpectedDelta)  # negative number
                self._update_moved_here(source, True)
                if not destArmyInterferedToo:
                    # intentionally do nothing about the dest tile diff if we found a source tile diff, as it is really unlikely that both source and dest get interfered with on same turn.
                    # TODO could be wrong
                    self._update_unexplained_delta(dest, 0)
                    self.last_player_index_submitted_move = last_player_index_submitted_move
                    return source, dest, move_half
        else:
            # nothing happened, we moved the expected army off of source. Not unexplained.
            self._update_unexplained_delta(source, 0)

        if hasDestDeltaMismatch:
            if dest.delta.lostSight:
                # then we got attacked, possibly BY the dest tile.
                if dest.delta.oldArmy > source.delta.oldArmy - 1 and dest.delta.oldOwner != self.player_index:
                    # then dest could have attacked us.
                    self._update_moved_here(dest, True)
                    dest.delta.imperfectArmyDelta = True
            else:
                if destHasEnDeltasNearby:
                    self._update_unexplained_delta(dest, destUnexpectedDelta)
                    self._update_moved_here(dest, True)


                if sourceHasEnPriorityDeltasNearby:
                    logbook.info(
                        f'MOVE {str(last_player_index_submitted_move)} with expectedDestDelta {expectedDestDelta} likely collided with destUnexpectedDelta {destUnexpectedDelta} at dest OR SOURCE based on actualDestDelta {actualDestDelta}.')
                else:
                    logbook.info(
                        f'MOVE {str(last_player_index_submitted_move)} with expectedDestDelta {expectedDestDelta} likely collided with destUnexpectedDelta {destUnexpectedDelta} at DEST based on actualDestDelta {actualDestDelta}.')

                # TODO this might need to also happen when lost sight, but idk how to get the right delta...? Repro...?
                if sourceHasEnPriorityDeltasNearby:
                    # the source tile could have been attacked for non-lethal damage BEFORE the move was made to target.
                    self._update_unexplained_delta(source, destUnexpectedDelta)
                    if dest.delta.oldOwner != self.player_index:
                        self._update_unexplained_delta(source, 0 - destUnexpectedDelta)
                    source.delta.imperfectArmyDelta = destHasEnDeltasNearby
                    self._update_moved_here(source, True)
                elif not destHasEnDeltasNearby:

                    if destUnexpectedDelta != 0:
                        self._update_moved_here(dest, True)
        else:
            logbook.info(
                f'!MOVE {str(last_player_index_submitted_move)} made it to dest with no issues, moving army.\r\n    expectedDestDelta {expectedDestDelta}, actualDestDelta {actualDestDelta}, expectedSourceDelta {expectedSourceDelta}, actualSrcDelta {actualSrcDelta}, sourceWasAttackedWithPriority {sourceWasAttackedWithPriority}, sourceWasCaptured {sourceWasCaptured}')
            self._update_unexplained_delta(dest, 0)
            # skip.add(dest)  # might not need this at alll.....? TODO ??

        if actualDestDelta == 0 and dest.delta.unexplainedDelta == 0:
            # then the move DEFINITELY didn't happen / was captured
            self.last_player_index_submitted_move = None
            return None
        
        self.last_player_index_submitted_move = last_player_index_submitted_move
        return source, dest, move_half

    def execute_definite_fog_island_capture(self, tileLost: Tile, killedByTile: Tile):
        # print(str(tile.army) + " : " + str(candidateTile.army))
        if killedByTile.visible:
            if tileLost.army + killedByTile.delta.armyDelta < -1 and killedByTile.player != -1:
                tileLost.player = killedByTile.player
                tileLost.delta.newOwner = killedByTile.player
                oldArmy = tileLost.army
                tileLost.army = 0 - killedByTile.delta.armyDelta - tileLost.army
                # THIS HANDLED EXTERNAL IN THE UPDATE LOOP, AFTER THIS LOGIC HAPPENS
                # if tile.isCity and isCityBonusTurn:
                #     tile.army += 1
                # if isArmyBonusTurn:
                #     tile.army += 1
                logbook.info(f" (islandFog 1) tile {str(tileLost)} army from {oldArmy} to {tileLost.army}")
                return 100
        elif tileLost.army - killedByTile.army < -1 and killedByTile.player != -1:
            tileLost.player = killedByTile.player
            tileLost.delta.newOwner = killedByTile.player
            oldArmy = tileLost.army
            tileLost.army = killedByTile.army - tileLost.army - 1
            oldCandArmy = killedByTile.army
            killedByTile.army = 1
            # THIS HANDLED EXTERNAL IN THE UPDATE LOOP, AFTER THIS LOGIC HAPPENS
            # if candidateTile.isCity and isCityBonusTurn:
            #     candidateTile.army += 1
            # if isArmyBonusTurn:
            #     candidateTile.army += 1
            logbook.info(f" (islandFog 2) tile {str(tileLost)} army from {oldArmy} to {tileLost.army}")
            logbook.info(
                f" (islandFog 2) candTile {killedByTile.toString()} army from {oldCandArmy} to {killedByTile.army}")
            return 100
        return -100

    def detect_movement_and_populate_unexplained_diffs(self):
        possibleMovesDict: typing.Dict[Tile, typing.List[Tile]] = {}

        self.unexplained_deltas = {}
        self.moved_here_set = set()
        for t in self.get_all_tiles():
            if t.delta.armyMovedHere:
                self.moved_here_set.add(t)
            if t.delta.unexplainedDelta == 0:
                continue
            if not t.visible:
                continue
            if t.player == -1:
                continue
            self.unexplained_deltas[t] = t.delta.unexplainedDelta

        for player in self.players:
            player.last_move = None

        if self.generals[self.player_index] is None or self.generals[self.player_index].player != self.player_index:
            # we are dead
            return

        for player in self.players:
            logbook.info(f'p{player.index} - unexplainedTileDelta {player.unexplainedTileDelta}, tileDelta {player.tileDelta}')

        # TODO debugging only
        logbook.info(f'Tiles with diffs pre-own: {str([str(t) for t in self.unexplained_deltas.keys()])}')
        logbook.info(f'Tiles with MovedHere pre-own: {str([str(t) for t in self.moved_here_set])}')

        # TRY OWN MOVE FIRST
        if self.last_player_index_submitted_move is not None:
            # check for dropped moves and apply the tile diffs from the players move ahead of time to more easily recognize other players moves.
            self.players[self.player_index].last_move = self._apply_last_player_move(self.last_player_index_submitted_move)
            if self.last_player_index_submitted_move is not None:
                src, dest, move_half = self.last_player_index_submitted_move

                # already logged
                self.set_tile_moved(
                    dest,
                    src,
                    fullFromDiffCovered=not src.delta.armyMovedHere,
                    fullToDiffCovered=not dest.delta.armyMovedHere,
                    byPlayer=self.player_index)

        skipCapturedPlayers: typing.List[int] = []
        for p in self.players:
            if p.dead and p.capturedBy is not None:
                skipCapturedPlayers.append(p.index)

        self.run_positive_delta_movement_scan(skipCapturedPlayers, possibleMovesDict, allowFogSource=False)

        self.run_attacked_tile_movement_scan(skipCapturedPlayers, possibleMovesDict, allowFogSource=False)

        self.run_positive_delta_movement_scan(skipCapturedPlayers, possibleMovesDict, allowFogSource=True)

        self.run_movement_into_fog_scan(skipCapturedPlayers, possibleMovesDict)

        self.run_attacked_tile_movement_scan(skipCapturedPlayers, possibleMovesDict, allowFogSource=True)

        self.run_island_vision_loss_scan(possibleMovesDict)

        # TODO for debugging only
        logbook.info(f'Tiles with diffs at end: {str([str(t) for t in self.unexplained_deltas.keys() if self.unexplained_deltas[t] != 0])}')
        logbook.info(f'Tiles with MovedHere at end: {str([str(t) for t in self.moved_here_set])}')

        for t in self.unexplained_deltas.keys():
            if t.delta.unexplainedDelta == 0:
                continue
            if not t.visible:
                continue
            if t.player == -1:
                continue
            if t in self.army_emergences:
                continue

            self.army_emergences[t] = (t.delta.unexplainedDelta, t.player)
            logbook.info(f'unexplained emergence {repr(t)} of {t.delta.unexplainedDelta}')

        return

    def calculate_player_deltas(self):
        myPlayer = self.players[self.player_index]

        lastScores = self.scoreHistory[1]
        if lastScores is None:
            logbook.info("no last scores?????")
            return

        expectedFriendlyDelta = 0

        for city in myPlayer.cities:
            if city.player != myPlayer.index:
                myPlayer.cityCount -= 1
                if city.player == -1:
                    continue

                self.players[city.player].cityCount = self.players[city.player].lastCityCount + 1

        if self.is_army_bonus_turn:
            expectedFriendlyDelta += myPlayer.tileCount
        if self.is_city_bonus_turn:
            expectedFriendlyDelta += myPlayer.cityCount

        actualMeDelta = myPlayer.score - lastScores[myPlayer.index].total
        actualFriendlyDelta = actualMeDelta

        if self.is_2v2:
            for teammate in self.teammates:
                teammatePlayer = self.players[teammate]
                if teammatePlayer.dead:
                    continue

                for city in teammatePlayer.cities:
                    if city.player != teammatePlayer.index:
                        teammatePlayer.cityCount -= 1
                        if city.player == -1:
                            continue

                        self.players[city.player].cityCount = self.players[city.player].lastCityCount + 1

                if self.is_army_bonus_turn:
                    expectedFriendlyDelta += teammatePlayer.tileCount
                if self.is_city_bonus_turn:
                    expectedFriendlyDelta += teammatePlayer.cityCount

                actualFriendlyDelta += teammatePlayer.score - lastScores[teammatePlayer.index].total

        friendlyFightDelta = expectedFriendlyDelta - actualFriendlyDelta

        logbook.info(f"myPlayer score {myPlayer.score}, lastScores myPlayer total {lastScores[myPlayer.index].total}, friendlyFightDelta {friendlyFightDelta} based on expectedFriendlyDelta {expectedFriendlyDelta} actualFriendlyDelta {actualFriendlyDelta}")

        teams = [i for i in range(len(self.players))]

        if self.teams is not None:
            teams = self.teams

        teamDict = {}

        for pIndex, teamIndex in enumerate(teams):
            if teamIndex == -1:
                continue
            teamList = teamDict.get(teamIndex, [])
            if len(teamList) == 0:
                teamDict[teamIndex] = teamList
            teamList.append(pIndex)

        for teamIndex, teamList in teamDict.items():
            teamCurrentCities = 0
            actualEnemyTeamDelta = 0
            expectedEnemyTeamDelta = 0
            teamCityCount = 0
            teamAlive = False
            for playerIndex in teamList:
                teamPlayer = self.players[playerIndex]

                if teamPlayer.dead:
                    teamPlayer.expectedScoreDelta = 0
                    teamPlayer.actualScoreDelta = 0
                    teamPlayer.cityCount = 0
                    teamPlayer.unexplainedTileDelta = 0
                    continue

                teamAlive = True

                if self.is_player_on_team_with(self.player_index, playerIndex):
                    teamPlayer.cityCount = len(teamPlayer.cities) + 1

                expectedEnemyDelta = 0
                if self.is_army_bonus_turn:
                    expectedEnemyDelta += teamPlayer.tileCount
                if self.is_city_bonus_turn:
                    expectedEnemyDelta += teamPlayer.cityCount

                logbook.info(
                    f'teamPlayer score {teamPlayer.score}, lastScores teamPlayer total {lastScores[teamPlayer.index].total}')

                teamPlayer.actualScoreDelta = teamPlayer.score - lastScores[teamPlayer.index].total
                teamPlayer.expectedScoreDelta = expectedEnemyDelta
                teamPlayer.knownScoreDelta += expectedEnemyDelta
                expectedEnemyTeamDelta += expectedEnemyDelta

                # potentialEnemyCities = teamPlayer.actualScoreDelta - teamPlayer.

                actualEnemyTeamDelta += teamPlayer.actualScoreDelta

                teamCurrentCities += teamPlayer.cityCount
                teamCityCount += teamPlayer.cityCount

            if not teamAlive:
                continue

            newCityCount = teamCityCount
            if self.remainingPlayers == 2 or self.is_2v2:
                # if NOT 1v1 we use the outer, dumber city count calculation that works reliably for FFA.
                # in a 1v1, if we lost army, then opponent also lost equal army (unless we just took a neutral tile)
                # this means we can still calculate city counts, even when fights are ongoing and both players are losing army
                # so we get the amount of unexpected delta on our player, and add that to actual opponent delta, and get the opponents city count

                realEnemyCities = actualEnemyTeamDelta + friendlyFightDelta - expectedEnemyTeamDelta + teamCurrentCities
                cityDifference = realEnemyCities - teamCurrentCities

                logbook.info(f'team{teamIndex} realEnemyCities {realEnemyCities} based on actualEnemyTeamDelta {actualEnemyTeamDelta}, friendlyFightDelta {friendlyFightDelta} (teamCurrentCities {teamCurrentCities}, expectedEnemyTeamDelta {expectedEnemyTeamDelta}, cityDifference {cityDifference})')

                if cityDifference <= -10:
                    # then opp just took a neutral city
                    newCityCount += 1
                    logbook.info(f"set team {teamIndex} cityCount += 1 to {newCityCount} because it appears they just took a city based on realEnemyCities {realEnemyCities}.")
                elif cityDifference >= 10:
                    # then our player just took a neutral city, noop
                    logbook.info(
                        f"WE just took a city? enemy team cityDifference {cityDifference} > 30 should only happen when we just took a city because of the effect on tiledelta. Ignoring realEnemyCities {realEnemyCities} this turn, realEnemyCities {realEnemyCities} >= 30 and actualEnemyTeamDelta {actualEnemyTeamDelta} < -30")
                elif self.is_city_bonus_turn and realEnemyCities != teamCurrentCities:
                    newCityCount = realEnemyCities
                    logbook.info(
                        f"want to set team {teamIndex} cityCount to {newCityCount}. "
                        f"\nexpectedFriendlyDelta {expectedFriendlyDelta}, actualFriendlyDelta {actualFriendlyDelta},"
                        f"\nexpectedEnemyTeamDelta {expectedEnemyTeamDelta}, actualEnemyTeamDelta {actualEnemyTeamDelta},"
                        f"\nfrFightDelta {friendlyFightDelta} results in realEnemyCities {realEnemyCities} vs teamCurrentCities {teamCurrentCities}")

            logbook.info(f'cities for team {teamIndex}, as {newCityCount} vs current {teamCurrentCities}?')

            if self.player_index in teamList:
                # we have perfect info of our own cities
                continue

            if self.remainingPlayers > 2 and self.is_2v2 and newCityCount - teamCurrentCities > 5 and teamCurrentCities > 1:
                logbook.info(f'miscounting cities for team {teamIndex}, as {newCityCount} vs current {teamCurrentCities}? ignoring')
                continue
            # if friendlyFightDelta == 0 or self.remainingPlayers == 2:
            logbook.info(f'Trying to make cities for team {teamIndex} match {newCityCount} vs current {teamCurrentCities}?')
            sum = 0
            for playerIndex in teamList:
                teamPlayer = self.players[playerIndex]
                if teamPlayer.dead:
                    continue
                sum += teamPlayer.cityCount
            iter = 0
            while sum < newCityCount and iter < 100:
                iter += 1
                for playerIndex in teamList:
                    teamPlayer = self.players[playerIndex]
                    if teamPlayer.dead:
                        continue
                    teamPlayer.cityCount += 1
                    teamPlayer.cityGainedTurn = self.turn
                    logbook.info(f'Incrementing p{playerIndex} cities by 1 from {teamPlayer.cityCount - 1} to {teamPlayer.cityCount}')
                    sum += 1
                    if sum >= newCityCount:
                        break

            while sum > newCityCount and iter < 100:
                iter += 1
                for playerIndex in teamList:
                    teamPlayer = self.players[playerIndex]
                    if teamPlayer.dead:
                        continue
                    teamPlayer.cityCount -= 1
                    teamPlayer.cityLostTurn = self.turn
                    logbook.info(f'Decrementing p{playerIndex} cities by 1 from {teamPlayer.cityCount + 1} to {teamPlayer.cityCount}')
                    sum -= 1
                    if sum <= newCityCount:
                        break

            if iter > 98:
                logbook.error('INFINITE LOOPED IN TEAM CITY HANDLER')
                raise AssertionError('INFINITE LOOPED IN TEAM CITY HANDLER')

        for player in self.players:
            playerDeltaDiff = player.actualScoreDelta - player.knownScoreDelta
            if playerDeltaDiff < 0:
                # either they're fighting someone, attacking a neutral city, attacking neutral tiles, or someone captured one of their cities.
                # first try whoever they were fighting last turn if any:
                if player.fighting_with_player >= 0:
                    teamPlayer = self.players[player.fighting_with_player]
                    otherPlayerDeltaDiff = teamPlayer.actualScoreDelta - teamPlayer.expectedScoreDelta
                    if otherPlayerDeltaDiff == playerDeltaDiff:
                        # already set to the right player, leave it alone
                        continue
                    elif otherPlayerDeltaDiff < 0:
                        # not as sure, here, but LIKELY still fighting the same player.
                        continue

                for teamPlayer in self.players:
                    if teamPlayer == player:
                        continue
                    otherPlayerDeltaDiff = teamPlayer.actualScoreDelta - teamPlayer.expectedScoreDelta
                    # if self.is_2v2 and self.teammates[player.index] == self.teammates[teamPlayer.index]:
                    #     teamPlayer = 0 - teamPlayer.expectedScoreDelta
                    if otherPlayerDeltaDiff == playerDeltaDiff:
                        # then these two are probably fighting each other!?!?!?!?
                        teamPlayer.fighting_with_player = player.index
                        player.fighting_with_player = teamPlayer.index
            elif player.knownScoreDelta == player.expectedScoreDelta:
                player.fighting_with_player = -1

    def _move_would_violate_known_player_deltas(self, source: Tile, dest: Tile):
        knowSourceOwner = source.was_visible_last_turn() or (self.remainingPlayers == 2 and source.discovered and source.player >= 0)
        wouldCapture = source.delta.oldArmy > dest.delta.oldArmy - 1 and not self.is_player_on_team_with(source.delta.oldOwner, dest.delta.oldOwner)
        wouldCapture = wouldCapture or (self.is_player_on_team_with(source.delta.oldOwner, dest.delta.oldOwner) and source.delta.oldOwner != dest.delta.oldOwner)

        if knowSourceOwner:
            sourceOwner = self.players[source.delta.oldOwner]
            if source.delta.gainedSight:
                sourceOwner = self.players[source.player]
            knowDestOwner = dest.was_visible_last_turn() or (self.remainingPlayers == 2 and dest.discovered and dest.delta.oldOwner >= 0)
            if knowDestOwner:
                destOwner = None

                if dest.delta.oldOwner >= 0:
                    destOwner = self.players[dest.delta.oldOwner]
                if sourceOwner == destOwner:
                    # ok we know the players are fighting with each other, we know one move attacked the source tile
                    if sourceOwner.unexplainedTileDelta == 1:
                        logbook.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} can be discarded '
                                     f'outright, as it would not have captured a tile and the player '
                                     f'DID capture a tile.')

                        return True

                elif self.remainingPlayers == 2 and destOwner is not None and destOwner.unexplainedTileDelta == 1:
                    logbook.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} can be discarded '
                                 f'outright, as it would have captured a tile and instead dest player'
                                 f' p{destOwner.index} gained tiles.')
                    return True

                elif self.remainingPlayers == 2 and sourceOwner.unexplainedTileDelta < 0:
                    logbook.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} can be discarded '
                                 f'outright, as it would have captured a tile and instead they lost at '
                                 f'least one net tile. This should be accurate unless the player is being '
                                 f'attacked by more than two players at once.')
                    return True

                elif self.remainingPlayers == 2 and sourceOwner.unexplainedTileDelta == 0 and wouldCapture:
                    logbook.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} is sketchy but allowed, '
                                 f'as it would have captured a tile and they did not gain tiles. TODO make this '
                                 f'more of a spectrum and weight these possible moves lower.')

        return False

    def set_fog_moved_from_army_incremented(self, tile: Tile, byPlayer: int, expectedDelta: int | None = None):
        army = 1

        if expectedDelta is not None:
            potentialArmy = tile.delta.oldArmy + expectedDelta
            if potentialArmy <= 0:
                self.set_fog_emergence(tile, 0 - expectedDelta, byPlayer)
                potentialArmy = 1
            army = potentialArmy

        tile.delta.oldArmy = army - expectedDelta

        # this gets done separately, later. WHy would we do it now...?
        # if self.is_army_bonus_turn:
        #     army += 1
        # if (tile.isCity or tile.isGeneral) and self.is_city_bonus_turn:
        #     army += 1

        tile.army = army
        tile.delta.oldOwner = byPlayer
        tile.delta.newOwner = byPlayer

    def set_fog_emergence(self, fromTile: Tile, armyEmerged: int, byPlayer: int):
        logbook.info(f'+++EMERGENCE {repr(fromTile)} = {armyEmerged}')
        self.army_emergences[fromTile] = (armyEmerged, byPlayer)

    def run_movement_into_fog_scan(
            self,
            skipCapturedPlayers,
            possibleMovesDict,
    ):
        """
        Handles moves into fog, or into tiles that BECAME fog, but NOT from tiles where we lost vision of the source and destination as part of the capture.

        @param skipCapturedPlayers:
        @param possibleMovesDict:
        @return:
        """
        logbook.info(f'Tiles with diffs at pre-FOG: {str([str(t) for t in self.unexplained_deltas.keys() if self.unexplained_deltas[t] != 0])}')
        logbook.info(f'Tiles with MovedHere at pre-FOG: {str([str(t) for t in self.moved_here_set])}')
        # now check for destinations into fog
        for x in range(self.cols):
            for y in range(self.rows):
                sourceTile = self.grid[y][x]
                if not sourceTile.delta.armyMovedHere:
                    continue
                if sourceTile.delta.imperfectArmyDelta:
                    continue
                if sourceTile.delta.oldOwner == self.player_index:
                    continue
                if sourceTile.delta.oldOwner in self.teammates:
                    continue
                if sourceTile.delta.oldOwner == -1 or sourceTile.delta.oldOwner in skipCapturedPlayers:
                    continue

                potentialDests = []
                sourceWasAttackedNonLethalOrVacated = sourceTile.delta.armyDelta < 0 and sourceTile.delta.oldOwner == sourceTile.delta.newOwner
                # sourceWasAttackedNonLethalOrVacated = sourceTile.delta.oldArmy + sourceTile.delta.armyDelta < sourceTile.delta.oldArmy
                for potentialDest in sourceTile.movable:
                    # if (potentialDest.visible or potentialDest.was_visible_last_turn()) and not potentialDest.delta.gainedSight:
                    if potentialDest.visible and not potentialDest.delta.gainedSight:
                        continue

                    if sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_dest_match(sourceTile, potentialDest):
                        logbook.info(
                            f'FOG SOURCE SCAN DEST {repr(potentialDest)} SRC {repr(sourceTile)} WAS sourceWasAttackedNonLethalOrVacated {sourceWasAttackedNonLethalOrVacated} FORCE-SELECTED DUE TO EXACT MATCH, BREAKING EARLY')
                        potentialDests = [potentialDest]
                        break
                    # prevents seeing moves into captured-player territory the turn after a capture
                    if potentialDest.delta.oldOwner in skipCapturedPlayers:
                        continue

                    if potentialDest.delta.imperfectArmyDelta and sourceWasAttackedNonLethalOrVacated:
                        logbook.info(
                            f'FOG SOURCE SCAN DEST {repr(potentialDest)} SRC {repr(sourceTile)} WAS potentialDest.delta.imperfectArmyDelta and sourceWasAttackedNonLethalOrVacated, INCLUDING IT AS POTENTIAL DEST')
                        potentialDests.append(potentialDest)
                    elif self._is_partial_army_movement_delta_match(source=sourceTile, dest=potentialDest):
                        logbook.info(
                            f'FOG SOURCE SCAN DEST {repr(potentialDest)} SRC {repr(sourceTile)} WAS self._is_partial_army_movement_delta_match(source=sourceTile, dest=potentialDest), INCLUDING IT AS POTENTIAL DEST')
                        potentialDests.append(potentialDest)

                potentialUsKillDests = [d for d in potentialDests if self.is_player_on_team_with(d.delta.oldOwner, self.player_index)]
                if len(potentialUsKillDests) == 1:
                    potentialDests = potentialUsKillDests

                if len(potentialDests) == 1:
                    exclusiveDest = potentialDests[0]
                    # we have our dest...?
                    exactMatch = True
                    if sourceTile.delta.imperfectArmyDelta:
                        exactMatch = False
                    if exclusiveDest.delta.imperfectArmyDelta and not exclusiveDest.delta.lostSight:
                        exactMatch = False
                    if not self._is_exact_army_movement_delta_dest_match(sourceTile, exclusiveDest):
                        exactMatch = False

                    # should have had perfect info of this tile for this case to get hit so should always be this.
                    byPlayer = sourceTile.delta.oldOwner
                    if byPlayer == -1:
                        byPlayer = sourceTile.player
                    if byPlayer == -1:
                        byPlayer = exclusiveDest.player
                    if byPlayer == -1:
                        # we can get here if they attacked a neutral city from fog
                        for adj in sourceTile.movable:
                            if adj.visible and self.is_tile_enemy(adj):
                                byPlayer = adj.player
                                break
                    if byPlayer == -1:
                        # we can get here if they attacked a neutral city from fog
                        for adj in sourceTile.movable:
                            if self.is_tile_enemy(adj):
                                byPlayer = adj.player
                                break

                    logbook.info(
                        f'FOG SOURCE SCAN DEST {repr(exclusiveDest)} SRC {repr(sourceTile)} WAS EXCLUSIVE DEST, EXACT MATCH {exactMatch} INCLUDING IN MOVES, CALCED PLAYER {byPlayer}')

                    self.set_tile_moved(
                        exclusiveDest,
                        sourceTile,
                        fullFromDiffCovered=exactMatch,
                        fullToDiffCovered=exactMatch,
                        byPlayer=byPlayer)
                else:
                    if len(potentialDests) > 0:
                        logbook.info(f'FOG SOURCE SCAN SRC {repr(sourceTile)} RESULTED IN MULTIPLE DESTS {repr([repr(s) for s in potentialDests])}, UNHANDLED FOR NOW')
                    possibleMovesDict[sourceTile] = potentialDests

    def run_island_vision_loss_scan(self, possibleMovesDict):
        # TODO for debugging only
        logbook.info(f'Tiles with diffs at pre-ISLAND-VISION-LOSS: {str([str(t) for t in self.unexplained_deltas.keys() if self.unexplained_deltas[t] != 0])}')
        logbook.info(f'Tiles with MovedHere at pre-ISLAND-VISION-LOSS: {str([str(t) for t in self.moved_here_set])}')
        # now check for island vision loss
        for x in range(self.cols):
            for y in range(self.rows):
                destTile = self.grid[y][x]

                if not destTile.delta.armyMovedHere:
                    continue
                if not destTile.delta.lostSight:
                    continue
                if destTile.delta.oldOwner != self.player_index and destTile.delta.oldOwner not in self.teammates:
                    continue

                potentialSources = []
                destWasAttackedNonLethalOrVacated = destTile.delta.armyDelta < 0  # and destTile.delta.oldOwner == destTile.delta.newOwner
                # destWasAttackedNonLethalOrVacated = True
                # destWasAttackedNonLethalOrVacated = destTile.delta.oldArmy + destTile.delta.armyDelta < destTile.delta.oldArmy

                # prefer most recently moved, followed by smallest capturer
                for potentialSource in sorted(destTile.movable, key=lambda t: (0 - t.lastMovedTurn, t.army)):
                    # we already track our own moves successfully prior to this.
                    if potentialSource.delta.oldOwner == self.player_index or potentialSource.delta.oldOwner in self.teammates or potentialSource.delta.oldOwner == -1:
                        continue
                    if not potentialSource.delta.lostSight:
                        logbook.info(f'ISLAND FOG DEST {repr(destTile)}: SRC {repr(potentialSource)} SKIPPED BECAUSE DIDNT LOSE VISION OF SOURCE, WHICH MEANS IT SHOULD HAVE BEEN CAUGHT BY ANOTHER HANDLER ALREADY (?)')
                        continue
                        # if potentialSource.visible and potentialSource.delta.unexplainedDelta == destTile.delta.unexplainedDelta:
                        #     # IF I DECIDE THIS SHOULD HANDLE VISIBLE UNCOMMENT THIS BLOCK AND FIX evaluate_island_fog_move TO HANDLE VISIBLE SOURCES
                        #     logbook.info(f'ISLAND FOG DEST FROM VISIBLE {repr(destTile)}: SRC {repr(potentialSource)} NOT SKIPPED')
                        #     continue
                        # else:
                        #     logbook.info(f'ISLAND FOG DEST {repr(destTile)}: SRC {repr(potentialSource)} SKIPPED BECAUSE DIDNT LOSE VISION OF SOURCE, WHICH MEANS IT SHOULD HAVE BEEN CAUGHT BY ANOTHER HANDLER ALREADY (?)')
                        #     continue
                    if evaluate_island_fog_move(destTile, potentialSource):
                        byPlayer = potentialSource.delta.oldOwner

                        logbook.info(
                            f'ISLAND FOG DEST {repr(destTile)} SRC {repr(potentialSource)} WAS EXCLUSIVE SOURCE, INCLUDING IN MOVES, CALCED PLAYER {byPlayer}')

                        self.set_tile_moved(
                            destTile,
                            potentialSource,
                            fullFromDiffCovered=True,
                            fullToDiffCovered=True,
                            byPlayer=byPlayer)

                        break

                else:
                    if len(potentialSources) > 0:
                        logbook.info(f'ISLAND FOG DEST {repr(destTile)} RESULTED IN MULTIPLE SOURCES {repr([repr(s) for s in potentialSources])}, UNHANDLED FOR NOW')
                    possibleMovesDict[destTile] = potentialSources

    def run_positive_delta_movement_scan(self, skipCapturedPlayers: typing.List[int], possibleMovesDict: typing.Dict[Tile, typing.List[Tile]], allowFogSource: bool):
        """
        Scan for moves TO a given tile
        """
        fogFlag = ""
        if allowFogSource:
            fogFlag = " (FOG)"

        # TODO for debugging only
        logbook.info(f'Tiles with diffs pre-POS{fogFlag}: {str([str(t) for t in self.unexplained_deltas.keys() if self.unexplained_deltas[t] != 0])}')
        logbook.info(f'Tiles with MovedHere pre-POS{fogFlag}: {str([str(t) for t in self.moved_here_set])}')

        # scan for tiles with positive deltas first, those tiles MUST have been gathered to from a friendly tile by the player they are on, letting us eliminate tons of options outright.
        for x in range(self.cols):
            for y in range(self.rows):
                destTile = self.grid[y][x]
                if not destTile.delta.armyMovedHere or destTile.delta.imperfectArmyDelta:
                    continue  # No imperfect army deltas, and skip if an army moved into us (why?)
                # TODO REMOVE? (? actually this looks like it prevents seeing moves into captured-player territory)
                if destTile.delta.oldOwner in skipCapturedPlayers:
                    continue

                potentialSources = []
                # destWasAttackedNonLethalOrVacatedOrUnmoved = destTile.delta.unexplainedDelta <= 0 and self._teams[destTile.delta.oldOwner] != self._teams[destTile.delta.newOwner]
                wasFriendlyMove = self.team_ids_by_player_index[destTile.delta.oldOwner] == self.team_ids_by_player_index[destTile.delta.newOwner] and destTile.delta.oldOwner != destTile.delta.newOwner
                destWasAttackedNonLethalOrVacatedOrUnmoved = destTile.delta.unexplainedDelta <= 0 and not wasFriendlyMove
                if destWasAttackedNonLethalOrVacatedOrUnmoved:
                    logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} SKIPPED BECAUSE destWasAttackedNonLethalOrVacatedOrUnmoved {destWasAttackedNonLethalOrVacatedOrUnmoved}')
                    continue

                for potentialSource in destTile.movable:
                    if potentialSource.delta.oldOwner == self.player_index:
                        # we already track our own moves successfully prior to this.
                        continue
                    if (
                            not allowFogSource
                            and (
                                    (not potentialSource.visible and not potentialSource.delta.lostSight)
                                    or potentialSource.delta.gainedSight
                            )
                    ):
                        continue
                    # if destWasAttackedNonLethalOrVacatedOrUnmoved and potentialSource.player != destTile.delta.oldOwner:
                    #     logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} <- SRC {repr(potentialSource)} SKIPPED BECAUSE destWasAttackedNonLethalOrVacatedOrUnmoved {destWasAttackedNonLethalOrVacatedOrUnmoved}')
                    #     continue
                    if potentialSource.delta.oldOwner in skipCapturedPlayers:
                        continue
                    if potentialSource.was_visible_last_turn() and self.team_ids_by_player_index[potentialSource.delta.oldOwner] != self.team_ids_by_player_index[destTile.delta.oldOwner] and self.player_index != destTile.player:
                        # only the player who owns the resulting tile can move one of their own tiles into it. TODO 2v2...?
                        logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} <- SRC {repr(potentialSource)} SKIPPED BECAUSE potentialSource.was_visible_last_turn() and potentialSource.delta.oldOwner != destTile.player')
                        continue
                    if destTile.delta.armyDelta > 0 and destTile.was_visible_last_turn() and potentialSource.was_visible_last_turn() and potentialSource.delta.armyDelta > 0:
                        msg = f'This shouldnt be possible, two of the same players tiles increasing on the same turn...? {repr(potentialSource)} - {repr(destTile)}'
                        if ENABLE_DEBUG_ASSERTS:
                            raise AssertionError(msg)
                        else:
                            logbook.error(msg)
                        # continue

                    sourceWasAttackedNonLethalOrVacated = potentialSource.delta.armyDelta < 0
                    # if  sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_match(potentialSource, destTile):
                    if sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_dest_match(potentialSource, destTile):
                        potentialSources = [potentialSource]
                        logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} <- SRC {repr(potentialSource)} FORCE-SELECTED DUE TO EXACT MATCH, BREAKING EARLY')
                        break

                    # no effect on diagonal
                    # if potentialSource.delta.imperfectArmyDelta and (not sourceWasAttackedNonLethalOrVacated or (potentialSource.player >= 0 and potentialSource.player != destTile.delta.oldOwner)):
                    if potentialSource.delta.imperfectArmyDelta and not self._move_would_violate_known_player_deltas(potentialSource, destTile):
                        logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} <- SRC {repr(potentialSource)} INCLUDED AS POTENTIAL SOURCE BUT CONTINUING TO LOOK FOR MORE')
                        potentialSources.append(potentialSource)
                    elif self.remainingPlayers > 2 and self._is_partial_army_movement_delta_match(source=potentialSource, dest=destTile):
                        if destTile.army < 3:
                            logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} <- SRC {repr(potentialSource)} refusing to include potential FFA third party attack because tile appears to have been moved, something seems messed up...')
                        else:
                            logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} <- SRC {repr(potentialSource)} including potential FFA third party attack from fog as tile damager.')
                            potentialSources.append(potentialSource)

                if len(potentialSources) == 1:
                    exclusiveSrc = potentialSources[0]
                    # we have our source...?
                    exactMatch = (
                            not destTile.delta.imperfectArmyDelta
                            and not exclusiveSrc.delta.imperfectArmyDelta
                            and self._is_exact_army_movement_delta_dest_match(exclusiveSrc, destTile)
                    )

                    logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} <- SRC {repr(exclusiveSrc)} WAS EXCLUSIVE SOURCE, EXACT MATCH {exactMatch} INCLUDING IN MOVES')

                    byPlayer = -1
                    if destTile.was_visible_last_turn() and destTile.delta.oldOwner == destTile.player:
                        byPlayer = destTile.player
                    if byPlayer == -1 and exclusiveSrc.was_visible_last_turn():
                        byPlayer = exclusiveSrc.delta.oldOwner
                    if byPlayer == -1:
                        byPlayer = exclusiveSrc.delta.oldOwner
                    if byPlayer == -1:
                        byPlayer = destTile.player

                    self.set_tile_moved(
                        destTile,
                        exclusiveSrc,
                        # fullFromDiffCovered=exactMatch, #both this and hardcoding true currently have the same result in tests...?
                        fullFromDiffCovered=True,
                        fullToDiffCovered=True,  # otherwise we try to find the fog move to this tile again. This being wrong should be exceedingly rare, like 3 players all moving to the same tile rare.
                        byPlayer=byPlayer)
                else:
                    if len(potentialSources) > 0:
                        logbook.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} RESULTED IN MULTIPLE SOURCES {repr([repr(s) for s in potentialSources])}, UNHANDLED FOR NOW')
                    possibleMovesDict[destTile] = potentialSources

    def run_attacked_tile_movement_scan(self, skipCapturedPlayers: typing.List[int], possibleMovesDict: typing.Dict[Tile, typing.List[Tile]], allowFogSource: bool):
        """
        Note, does not support attacks INTO fog (or attacks that BECAME fog).
        Then attacked dest tiles. This should catch obvious moves from fog as well as all moves between visible tiles.
        currently also catches moves into fog, which it shouldnt...? (TODO IS THIS STILL TRUE?)

        @param skipCapturedPlayers:
        @param possibleMovesDict:
        @param allowFogSource:
        @return:
        """
        fogFlag = ""
        if allowFogSource:
            fogFlag = "(FOG) "

        # TODO for debugging only
        logbook.info(f'Tiles with diffs pre-ATTK{fogFlag}: {str([str(t) for t in self.unexplained_deltas.keys() if self.unexplained_deltas[t] != 0])}')
        logbook.info(f'Tiles with MovedHere pre-ATTK{fogFlag}: {str([str(t) for t in self.moved_here_set])}')

        for x in range(self.cols):
            for y in range(self.rows):
                destTile = self.grid[y][x]
                # if not destTile.delta.armyMovedHere:
                if not destTile.delta.armyMovedHere or destTile.delta.imperfectArmyDelta:
                    continue
                if not allowFogSource and not destTile.visible and not destTile.delta.lostSight:
                    continue
                # TODO REMOVE (? actually this looks like it prevents seeing moves into captured-player territory)
                if destTile.delta.oldOwner in skipCapturedPlayers:
                    continue

                potentialSources = []
                wasFriendlyMove = self.team_ids_by_player_index[destTile.delta.oldOwner] == self.team_ids_by_player_index[destTile.delta.newOwner]
                destWasAttackedNonLethalOrVacated = destTile.delta.armyDelta < 0 and wasFriendlyMove
                # destWasAttackedNonLethalOrVacated = True
                # destWasAttackedNonLethalOrVacated = destTile.delta.oldArmy + destTile.delta.armyDelta < destTile.delta.oldArmy
                for potentialSource in destTile.movable:
                    # we already track our own moves successfully prior to this.
                    if potentialSource.delta.oldOwner == self.player_index:
                        continue
                    if not allowFogSource and not potentialSource.visible and not potentialSource.delta.lostSight:
                        continue
                    if potentialSource.delta.oldOwner in skipCapturedPlayers:
                        continue
                    if potentialSource.was_visible_last_turn() and potentialSource.delta.oldOwner == -1:
                        continue
                    if potentialSource.delta.armyDelta > 0 and not potentialSource.delta.gainedSight:
                        logbook.info(
                            f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)}: SRC {repr(potentialSource)} SKIPPED BECAUSE GATHERED TO, NOT ATTACKED. potentialSource.delta.armyDelta > 0')
                        # then this was DEFINITELY gathered to, which would make this not a potential source. 2v2 violates this
                        continue
                    wasFriendlyMove = self.team_ids_by_player_index[potentialSource.delta.oldOwner] == self.team_ids_by_player_index[potentialSource.delta.newOwner] and potentialSource.delta.oldOwner != potentialSource.delta.newOwner
                    sourceWasAttackedNonLethalOrVacated = (
                            (potentialSource.delta.unexplainedDelta <= 0 and not wasFriendlyMove)
                            or potentialSource.delta.lostSight
                            or (not potentialSource.visible and allowFogSource)
                    )
                    # sourceWasAttackedNonLethalOrVacated = potentialSource.delta.armyDelta < 0 or potentialSource.delta.lostSight or (not potentialSource.visible and allowFogSource)
                    # if  sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_match(potentialSource, destTile):
                    if sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_dest_match(potentialSource, destTile):
                        potentialSources = [potentialSource]
                        logbook.info(
                            f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} FORCE-SELECTED DUE TO EXACT MATCH, BREAKING EARLY')
                        break

                    # no effect on diagonal
                    if (
                            potentialSource.delta.imperfectArmyDelta
                            and not destWasAttackedNonLethalOrVacated
                            # no effect on diagonal
                            # and (
                            #     not sourceWasAttackedNonLethalOrVacated
                            #     or (potentialSource.player >= 0 and potentialSource.player != destTile.delta.oldOwner)
                            # )
                            and not self._move_would_violate_known_player_deltas(potentialSource, destTile)
                    ):
                        potentialSources.append(potentialSource)
                    if destWasAttackedNonLethalOrVacated and self.remainingPlayers > 2 and self._is_partial_army_movement_delta_match(
                            source=potentialSource, dest=destTile):
                        if destTile.army < 3:
                            logbook.info(
                                f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} refusing to include potential FFA third party attack because tile appears to have been moved, something seems messed up...')
                        else:
                            logbook.info(
                                f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} including potential FFA third party attack from fog as tile damager.')
                            potentialSources.append(potentialSource)

                if len(potentialSources) == 1:
                    exclusiveSrc = potentialSources[0]
                    # we have our source...?
                    exactDestMatch = (
                            not destTile.delta.imperfectArmyDelta
                            and not exclusiveSrc.delta.imperfectArmyDelta
                            and self._is_exact_army_movement_delta_dest_match(exclusiveSrc, destTile)
                    )
                    exactSourceMatch = exactDestMatch

                    byPlayer = exclusiveSrc.delta.oldOwner
                    if byPlayer == -1:
                        # we can get here if they attacked a neutral city from fog
                        for adj in exclusiveSrc.movable:
                            if adj.visible and self.is_tile_enemy(adj):
                                byPlayer = adj.player
                                break
                    if byPlayer == -1:
                        # we can get here if they attacked a neutral city from fog
                        for adj in exclusiveSrc.movable:
                            if self.is_tile_enemy(adj):
                                byPlayer = adj.player
                                break
                    if byPlayer == -1 or self.players[byPlayer].last_move is not None:
                        byPlayer = self.players[destTile.delta.oldOwner].fighting_with_player
                    if byPlayer == -1:
                        possibilities = list(filter(lambda p: (
                                not p.dead
                                and not p.leftGame
                                and p.last_move is None
                                and p.unexplainedTileDelta < 0
                                and p.index != self.player_index
                                and p.index != destTile.delta.oldOwner
                        ), self.players))
                        if len(possibilities) > 0:
                            byPlayer = possibilities[0].index

                    logbook.info(
                        f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(exclusiveSrc)} WAS EXCLUSIVE SOURCE, EXACT MATCH {exactDestMatch} INCLUDING IN MOVES, CALCED PLAYER {byPlayer}')

                    if byPlayer != -1:
                        self.set_tile_moved(
                            destTile,
                            exclusiveSrc,
                            fullFromDiffCovered=exactSourceMatch,
                            fullToDiffCovered=exactDestMatch,
                            byPlayer=byPlayer)
                    else:
                        logbook.error(
                            f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(exclusiveSrc)} UNABLE TO EXECUTE DUE TO UNABLE TO FIND byPlayer THAT ISNT NEUTRAL')
                else:
                    if len(potentialSources) > 0:
                        logbook.info(
                            f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} RESULTED IN MULTIPLE SOURCES {repr([repr(s) for s in potentialSources])}, UNHANDLED FOR NOW')
                    possibleMovesDict[destTile] = potentialSources

    def was_captured_this_turn(self, tile: Tile) -> bool:
        """Returns true if the tile was definitely captured THIS TURN by the player who now owns the tile"""
        if tile.delta.gainedSight:
            return False
        if tile.delta.oldOwner == tile.player:
            return False

        return True

    def handle_game_result(self, won: bool, killer: int = -1):
        self.result = won
        self.complete = True
        if killer >= 0:
            self.players[self.player_index].capturedBy = killer

    def get_tile_index_by_x_y(self, x: int, y: int) -> int:
        return y * self.cols + x

    def get_tile_by_tile_index(self, tileIndex: int) -> Tile:
        return self.tiles_by_index[tileIndex]

    def convert_tile_server_index_to_x_y(self, tileIndex: int) -> typing.Tuple[int, int]:
        y = tileIndex // self.cols
        x = tileIndex % self.cols
        return x, y

    def get_distance_between_or_none(self, tileA: Tile, tileB: Tile) -> int | None:
        return self.distance_mapper.get_distance_between_or_none(tileA, tileB)

    def get_distance_between(self, tileA: Tile, tileB: Tile) -> int:
        return self.distance_mapper.get_distance_between(tileA, tileB)

    def get_distance_2d_array_including_obstacles(self, tile: Tile) -> typing.List[typing.List[int]]:
        """
        Includes the distance to mountains / undiscovered obstacles (but does not path to the other side of them).
        DO NOT MODIFY THE OUTPUT FROM THIS METHOD.

        @param tile:
        @return:
        """
        matrix = self.distance_mapper.get_tile_dist_matrix(tile)
        # Because we know this will be mapmatrix, not dict, we hack this here and ignore the warning.
        # noinspection PyUnresolvedReferences
        return matrix.grid

    def get_distance_matrix_including_obstacles(self, tile: Tile) -> typing.Dict[Tile, int]:
        """
        Includes the distance to mountains / undiscovered obstacles (but does not path to the other side of them).

        @param tile:
        @return:
        """

        return self.distance_mapper.get_tile_dist_matrix(tile)

    def is_tile_visible_to(self, tile: Tile, player: int) -> bool:
        team = self.team_ids_by_player_index[player]
        for adj in tile.adjacents:
            if self.is_tile_on_team(adj, team):
                return True

        return False

    @staticmethod
    def _build_teams_array(map: MapBase) -> typing.List[int]:
        teams = [i for i in range(len(map.players))]
        if map.teams is not None:
            teams = [t for t in map.teams]

        teams.append(-1)  # put -1 at the end so that if -1 gets passed as the array index, the team is -1 for -1.

        return teams

    @staticmethod
    def get_teams_array(map: MapBase) -> typing.List[int]:
        return map.team_ids_by_player_index

    def get_teammates(self, player: int) -> typing.List[int]:
        """
        INCLUDES the player that was requested in the output.
        DO NOT MODIFY the resulting list.
        """
        return self._teammates_by_player[player]

    def get_teammates_no_self(self, player: int) -> typing.List[int]:
        """
        DOES NOT include the player that was requested in the output. So in an FFA or 1v1, the returned list will always be empty.
        DO NOT MODIFY the resulting list.
        """
        return self._teammates_by_player_no_self[player]

    def clone(self) -> MapBase:
        newMap = deepcopy(self)
        return newMap

    def _update_unexplained_delta(self, tile: Tile, newValue: int):
        tile.delta.unexplainedDelta = newValue
        if newValue == 0:
            self.unexplained_deltas.pop(tile, None)
        else:
            self.unexplained_deltas[tile] = newValue

    def _update_moved_here(self, tile: Tile, isMovedHere: bool):
        if tile.delta.armyMovedHere and not isMovedHere:
            tile.delta.armyMovedHere = False
            self.moved_here_set.discard(tile)
        elif not tile.delta.armyMovedHere and isMovedHere:
            tile.delta.armyMovedHere = True
            self.moved_here_set.add(tile)


class Map(MapBase):
    """
    Actual live server map that interacts with the crazy array patch diffs.
    """
    def __init__(self, start_data, data):
        # Start Data

        self.stars: typing.List[int] = [0 for x in range(16)]
        self._start_data = start_data
        replay_url = _REPLAY_URLS["na"] + start_data['replay_id']  # String Replay URL # TODO: Use Client Region

        # First Game Data, sets up all the private server-array-style-tile-caches
        self._apply_server_patch(data)

        map_grid_y_x: typing.List[typing.List[Tile]] = [[Tile(x, y, tileIndex=self.get_tile_index_by_x_y(x, y)) for x in range(self.cols)] for y in range(self.rows)]
        teams = None
        if 'teams' in start_data:
            teams = start_data['teams']

        mods = []
        if 'options' in start_data and 'modifiers' in start_data['options']:
            mods = start_data['options']['modifiers']
        super().__init__(start_data['playerIndex'], teams, start_data['usernames'], data['turn'], map_grid_y_x, replay_url, start_data['replay_id'], mods)

        self.apply_server_update(data)

    def __getstate__(self):
        state = super().__getstate__()

        return state

    def __setstate__(self, state):
        super().__dict__.update(state)

    def apply_server_update(self, data):
        self._apply_server_patch(data)

        self.update_turn(data['turn'])

        self.update_scores(Score.from_server_scores(self._get_raw_scores_from_data(data)))

        self.lookouts = set()

        self.observatories = set()

        # Check each tile for updates indiscriminately
        for x in range(self.cols):
            for y in range(self.rows):
                tile_type = self._tile_grid[y][x]
                army_count = self._army_grid[y][x]
                isCity = (y, x) in self._visible_cities
                isGeneral = (y, x) in self._visible_generals

                self.update_visible_tile(x, y, tile_type, army_count, isCity, isGeneral)

        mapResult = self.update()

        if 'stars' in data:
            self.stars[:] = data['stars']

        for player in self.players:
            player.stars = self.stars[player.index]

        return mapResult

    def _handle_server_game_result(self, result: str, data: typing.Dict[str, int] | None) -> bool:
        killer = -1
        if data is not None and 'killer' in data:
            killer = data['killer']
        won = result == "game_won"

        self.handle_game_result(won=won, killer=killer)

        return self.result

    def _get_raw_scores_from_data(self, data):
        scores = {s['i']: s for s in data['scores']}
        scores = [scores[i] for i in range(len(scores))]

        return scores

    def _apply_server_patch(self, data):
        if not '_map_private' in dir(self):
            self._map_private = []
            self._cities_private = []

        _apply_diff(self._map_private, data['map_diff'])
        _apply_diff(self._cities_private, data['cities_diff'])

        # Get Number Rows + Columns
        self.rows, self.cols = self._map_private[1], self._map_private[0]

        # Create Updated Tile Grid
        self._tile_grid = [[self._map_private[2 + self.cols * self.rows + y * self.cols + x] for x in range(self.cols)]
                           for y in range(self.rows)]
        # Create Updated Army Grid
        self._army_grid = [[self._map_private[2 + y * self.cols + x] for x in range(self.cols)] for y in
                           range(self.rows)]

        # Update Visible Cities
        self._visible_cities = [(c // self.cols, c % self.cols) for c in self._cities_private]  # returns [(y,x)]

        # Update Visible Generals
        self._visible_generals = [(-1, -1) if g == -1 else (g // self.cols, g % self.cols) for g in
                                  data['generals']]  # returns [(y,x)]


def new_map_grid(map, initialValueXYFunc):
    return [[initialValueXYFunc(x, y) for y in range(map.rows)] for x in range(map.cols)]


def new_tile_grid(map, initialValueTileFunc: typing.Callable[[Tile], T]) -> typing.List[typing.List[T]]:
    return [[initialValueTileFunc(map.grid[y][x]) for y in range(map.rows)] for x in range(map.cols)]


# cur fastest, 0.0185
# def new_value_grid(map, initValue) -> typing.List[typing.List[int]]:
#     return [[initValue] * map.rows for _ in range(map.cols)]


def new_value_grid(map, initValue: T) -> typing.List[typing.List[T]]:
    return [[initValue] * map.rows for _ in range(map.cols)]


def evaluate_island_fog_move(tile: Tile, candidateTile: Tile) -> bool:
    if tile.visible or candidateTile.visible:
        raise AssertionError(f"wtf, can't call this for visible tiles my guy. tile {repr(tile)} candidateTile {repr(candidateTile)} ")

    if tile.army - candidateTile.army < -1 and candidateTile.player != -1:
        return True
    return False


def _apply_diff(cache, diff):
    i = 0
    a = 0
    while i < len(diff) - 1:
        # offset and length
        a += diff[i]
        n = diff[i + 1]

        cache[a:a + n] = diff[i + 2:i + 2 + n]
        a += n
        i += n + 2

    if i == len(diff) - 1:
        cache[:] = cache[:a + diff[i]]
        i += 1

    assert i == len(diff)
