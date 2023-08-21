'''
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Map: Objects for representing Generals IO Map and Tiles
'''
import logging
import typing
import uuid

TILE_EMPTY = -1
TILE_MOUNTAIN = -2
TILE_FOG = -3
TILE_OBSTACLE = -4

_REPLAY_URLS = {
    'na': "http://generals.io/replays/",
    'eu': "http://eu.generals.io/replays/",
}


class Player(object):
    def __init__(self, player_index):
        self.cities: typing.List[Tile] = []
        self.general: Tile | None = None
        self.index = player_index
        self.stars = 0
        self.score = 0
        self.tiles: typing.List[Tile] = []
        self.tileCount = 0
        self.standingArmy = 0
        self.cityCount = 1
        self.cityLostTurn = 0
        self.cityGainedTurn = 0
        self.delta25tiles = 0
        self.delta25score = 0
        self.dead = False
        self.leftGame = False
        self.leftGameTurn = -1
        self.capturedBy = None
        self.knowsKingLocation = False

    def __str__(self):
        return f'p{self.index}{"(dead)" if self.dead else ""}: tiles {self.tileCount}, standingArmy {self.standingArmy}, general {str(self.general)}'


class TileDelta(object):
    def __init__(self):
        # Public Properties
        self.oldOwner = -1
        self.newOwner = -1
        self.gainedSight = False
        self.lostSight = False
        # true when this was a friendly tile and was captured
        self.friendlyCaptured = False
        self.armyDelta = 0
        """
        Positive means friendly army was moved ON to this tile (or army bonuses happened), 
        negative means army moved off or was attacked for not full damage OR was captured by opp.
        This includes city/turn25 army bonuses, so should ALWAYS be 0 UNLESS a player interacted 
        with the tile (or the tile was just discovered?). A capped neutral tile will have a negative army delta.
        """

        self.fromTile: Tile | None = None
        """If this tile is suspected to have been the target of a move last turn, this is the tile the map algo thinks the move is from."""

        self.toTile: Tile | None = None
        """If this tile is suspected to have had its army moved, this is the tile the map algo thinks it moved to."""

        self.armyMovedHere: bool = False
        """Indicates whether the tile update thinks an army MAY have moved here."""

        self.expectedDelta: int = 0
        """The EXPECTED army delta of the tile, this turn."""

    def __getstate__(self):
        state = self.__dict__.copy()

        if self.fromTile is not None:
            state["fromTile"] = f'{self.fromTile.x},{self.fromTile.y}'
        if self.toTile is not None:
            state["toTile"] = f'{self.toTile.x},{self.toTile.y}'
        return state

    def __setstate__(self, state):
        if state['fromTile'] is not None:
            x, y = state['fromTile'].split(',')
            state["fromTile"] = Tile(int(x), int(y))
        if state['toTile'] is not None:
            x, y = state['toTile'].split(',')
            state["toTile"] = Tile(int(x), int(y))
        self.__dict__.update(state)

class Tile(object):
    def __init__(self, x, y, tile=TILE_EMPTY, army=0, isCity=False, isGeneral=False, player: typing.Union[None, int] = None, isMountain=False,
                 turnCapped=0):
        # Public Properties
        self.x = x
        """Integer X Coordinate"""

        self.y = y
        """Integer Y Coordinate"""

        self.tile: int = tile
        """Integer Tile Type (TILE_OBSTACLE, TILE_FOG, TILE_MOUNTAIN, TILE_EMPTY, or 0-8 player_ID)"""

        self.turn_captured: int = turnCapped
        """Integer Turn Tile Last Captured"""

        self.army: int = army
        """Integer Army Count"""

        self.isCity: bool = isCity
        """Boolean isCity"""

        self.isGeneral: bool = isGeneral
        """Boolean isGeneral"""

        self._player: int = -1
        if player is not None:
            self._player = player
        elif tile >= 0:
            self._player = tile

        self.visible: bool = False
        self.discovered: bool = False
        self.discoveredAsNeutral: bool = False
        self.lastSeen: int = -1
        """Turn the tile was last seen"""

        self.isMountain: bool = isMountain

        self.delta: TileDelta = TileDelta()
        """Tile's army/player/whatever delta since last turn"""

        self.adjacents: typing.List[Tile] = []
        """Tiles VISIBLE from this tile (not necessarily movable, includes diagonals)"""

        self.movable: typing.List[Tile] = []
        """Tiles movable (left right up down) from this tile, including mountains, cities, obstacles."""

    def __getstate__(self):
        state = self.__dict__.copy()
        if "movable" in state:
            del state["movable"]
        if "adjacents" in state:
            del state["adjacents"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.movable = []
        self.adjacents = []

    @property
    def isNeutral(self) -> bool:
        """True if neutral and not a mountain or undiscovered obstacle"""
        return self._player == -1 and not self.isNotPathable

    @property
    def isUndiscoveredObstacle(self) -> bool:
        """True if not discovered and is a map obstacle/mountain"""
        return not self.discovered and self.tile == TILE_OBSTACLE

    @property
    def isNotPathable(self) -> bool:
        """True if mountain or undiscovered obstacle, but NOT for discovered neutral city"""
        return self.isMountain or self.isUndiscoveredObstacle

    @property
    def isPathable(self) -> bool:
        """False if mountain or undiscovered obstacle, True for all other tiles INCLUDING for discovered neutral cities"""
        return not self.isNotPathable

    @property
    def isObstacle(self) -> bool:
        """True if mountain, undiscovered obstacle, or discovered neutral city"""
        return self.isMountain or self.isUndiscoveredObstacle or (self.isCity and self.isNeutral)

    @property
    def player(self) -> int:
        """int player index"""
        return self._player

    @player.setter
    def player(self, value):
        if value >= 0:
            self.tile = value
        elif value == -1 and self.army == 0 and not self.isNotPathable and not self.isCity:
            self.tile = TILE_EMPTY # this whole thing seems wrong, needs to be updated carefully with tests as the delta logic seems to rely on it...
        self._player = value

    def __repr__(self):
        return f"({self.x:d},{self.y:d}) t{self.tile:d} a({self.army:d})"

    '''def __eq__(self, other):
            return (other != None and self.x==other.x and self.y==other.y)'''

    def __lt__(self, other):
        if other is None:
            return False
        return self.army < other.army

    def __gt__(self, other):
        if other is None:
            return True
        return self.army > other.army

    def __str__(self) -> str:
        return self.toString()

    def toString(self) -> str:
        return f"{self.x},{self.y}"

    def __hash__(self):
        return hash((self.x, self.y))

    def __eq__(self, other):
        if isinstance(other, Tile):
            return self.x == other.x and self.y == other.y
        return False

    # returns true if an army was likely moved to this tile, false if not.
    def update(
        self,
        map,
        tile: int,
        army: int,
        isCity=False,
        isGeneral=False,
        overridePlayer: int | None = None
    ) -> bool:
        self.delta = TileDelta()
        if tile >= TILE_MOUNTAIN:
            self.discovered = True
            self.lastSeen = map.turn
            if not self.visible:
                self.delta.gainedSight = True
                self.visible = True

        armyMovedHere = False

        self.delta.oldOwner = self._player

        if self.tile != tile:  # tile changed
            if tile < TILE_MOUNTAIN and self.discovered:  # lost sight of tile.
                self.delta.lostSight = True
                self.visible = False
                self.lastSeen = map.turn - 1

                if self._player == map.player_index or self._player in map.teammates:
                    # we lost the tile
                    # TODO Who might have captured it? for now set to unowned.
                    self.delta.friendlyCaptured = True
                    logging.info(f'tile captured, losing vision, army moved here true for {str(self)}')
                    armyMovedHere = True
                    self._player = -1
            elif tile == TILE_MOUNTAIN:
                self.isMountain = True
            elif tile >= 0:
                self._player = tile

            self.tile = tile

        # can only 'expect' army deltas for tiles we can see. Visible is already calculated above at this point.
        if self.visible:
            expectedDelta: int = 0
            if (self.isCity or self.isGeneral) and self.player >= 0 and map.turn % 2 == 0:
                expectedDelta += 1

            if self.player >= 0 and map.turn % 50 == 0:
                expectedDelta += 1

            self.delta.expectedDelta = expectedDelta

        self.delta.newOwner = self._player
        if overridePlayer is not None:
            self.delta.newOwner = overridePlayer
            self._player = overridePlayer

        if self.visible:  # Remember Discovered Armies
            oldArmy = self.army
            # logging.info("assigning tile {} with oldArmy {} new army {}?".format(self.toString(), oldArmy, army))
            self.army = army
            if self.delta.oldOwner != self.delta.newOwner:
                # tile captures happen before bonuses, so the new owner gets any expected delta.
                # city with 3 on turn 49, gets captured by a 4 army. Army is 3 again on 50 with city+army bonus, the delta should be -4
                #                      0 - (3  +  3 - 2) = -4
                self.delta.armyDelta = 0 - (self.army + oldArmy - self.delta.expectedDelta)
            else:
                # city with 3 on turn 49, moves 2 army to tile adjacent. Army is 3 again on 50 with city+army bonus, the delta should be -2
                # city with 3 on turn 49, gets attacked for 2 by enemy. Army is 3 again on 50 with city+army bonus, the delta should be -2
                # city with 3 on turn 49 does nothing, armyDelta should be 0 when it has 5 army on 50
                self.delta.armyDelta = self.army - (oldArmy + self.delta.expectedDelta)

            if self.delta.armyDelta != 0:
                armyMovedHere = True

        if isCity:
            self.isCity = True
            self.isGeneral = False
            # if self in map.cities:
            #	map.cities.remove(self)
            # map.cities.append(self)
            # TODO remove, this should NOT happen here
            if not self in map.cities:
                map.cities.append(self)

            # playerObj = map.players[self._player]

            # if not self in playerObj.cities:
            #	playerObj.cities.append(self)

            # TODO remove, this should NOT happen here
            if self in map.generals:
                map.generals[self._general_index] = None
        elif isGeneral:
            playerObj = map.players[self._player]
            playerObj.general = self
            self.isGeneral = True
            # TODO remove, this should NOT happen here
            map.generals[tile] = self
            self._general_index = self.tile

        if self.delta.oldOwner != self.delta.newOwner:
            # TODO  and not self.delta.gainedSight ?
            logging.info(f'oldOwner != newOwner for {str(self)}')
            armyMovedHere = True

        # if self.delta.oldOwner == self.delta.newOwner and self.delta.armyDelta == 0:
        #     armyMovedHere = False

        self.delta.armyMovedHere = armyMovedHere

        if armyMovedHere:
            logging.info(f'armyMovedHere True for {str(self)} (expected delta was {self.delta.expectedDelta}, actual was {self.delta.armyDelta})')

        return armyMovedHere


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




class MapBase(object):
    def __init__(self,
                 player_index: int,
                 teams: typing.Union[None, typing.List[int]],  # the players index into this array gives the index of their teammate as the value.
                 user_names: typing.List[str],
                 turn: int,
                 map_grid_y_x: typing.List[typing.List[Tile]],  # dont need to init movable and stuff
                 replay_url: str,
                 replay_id: typing.Union[None, str] = None
                 ):
        # Start Data
        self.player_index: int = player_index  # Integer Player Index
        # TODO TEAMMATE
        self.teammates = set()
        if teams is not None:
            for player, team in enumerate(teams):
                if team == teams[self.player_index] and player != self.player_index:
                    self.teammates.add(player)

        self.usernames: typing.List[str] = user_names  # List of String Usernames
        self.players = [Player(x) for x in range(len(self.usernames))]
        self.pathableTiles: typing.Set[Tile] = set()
        """Tiles PATHABLE from the general spawn on the map, including neutral cities but not including mountains/undiscovered obstacles"""

        self.reachableTiles: typing.Set[Tile] = set()
        """
        Tiles REACHABLE from the general spawn on the map, this includes EVERYTHING from pathableTiles but ALSO 
        includes mountains and undiscovered obstacles that are left/right/up/down adjacent to anything in pathableTiles
        """

        self.notify_tile_captures = []
        self.notify_tile_deltas = []
        self.notify_city_found = []
        self.notify_tile_discovered = []
        self.notify_tile_revealed = []
        self.notify_general_revealed = []
        self.notify_player_captures = []

        # First Game Data
        # self._applyUpdateDiff(data)
        self.rows: int = len(map_grid_y_x)  # Integer Number Grid Rows
        self.cols: int = len(map_grid_y_x[0])  # Integer Number Grid Cols
        self.grid: typing.List[typing.List[Tile]] = map_grid_y_x
        self.army_moved_grid: typing.List[typing.List[bool]] = []

        # List of 8 Generals (None if not found)
        self.generals: typing.List[typing.Union[Tile, None]] = [
            None
            for x
            in range(8)]

        self.init_grid_movable()

        self.turn: int = turn  # Integer Turn # (1 turn / 0.5 seconds)
        # List of City Tiles. Need concept of hidden cities from sim..? or maintain two maps, maybe. one the sim maintains perfect knowledge of, and one for each bot with imperfect knowledge from the sim.
        self.cities: typing.List[Tile] = []
        self.replay_url = replay_url
        self.replay_id = replay_id
        if self.replay_id is None:
            self.replay_id = f'TEST__{str(uuid.uuid4())}'

        self.scores: typing.List[Score] = [Score(x, 0, 0, False) for x in range(8)]  # List of Player Scores

        self.complete: bool = False
        """Game Complete"""

        self.result: bool = False
        """Game Result (True = Won)"""

        self.scoreHistory: typing.List[typing.Union[None, typing.List[Score]]] = [None for i in range(25)]
        self.remainingPlayers = 0

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
        if 'notify_tile_revealed' in state:
            del state['notify_tile_revealed']
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
        self.notify_tile_revealed = []
        self.notify_general_revealed = []
        self.notify_player_captures = []

    def get_all_tiles(self) -> typing.Generator[Tile, None, None]:
        for row in self.grid:
            for tile in row:
                yield tile


    def GetTile(self, x, y) -> typing.Union[None, Tile]:
        if x < 0 or x >= self.cols or y < 0 or y >= self.rows:
            return None
        return self.grid[y][x]

    def _update_player_information(self):
        cityCounts = [0 for i in range(len(self.players))]
        for player in self.players:
            # print("player {}".format(player.index))
            player.score = self.scores[player.index].total
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
                    if not player.leftGame:
                        player.leftGame = True
                        player.leftGameTurn = self.turn
                    # don't immediately set 'dead' so that we keep attacking disconnected player
                    if self.scores[i].tiles == 0:
                        player.dead = True
                else:
                    self.remainingPlayers += 1

        if self.remainingPlayers == 2:
            self.calculate_player_city_counts_1v1()
        elif self.remainingPlayers > 2:
            for i, player in enumerate(self.players):
                if not player.dead and player.index != self.player_index:
                    if player.cityCount < cityCounts[i]:
                        player.cityCount = cityCounts[i]
                        player.cityGainedTurn = self.turn
                    if player.cityCount > cityCounts[i] and cityCounts[i] > 0:
                        player.cityCount = cityCounts[i]
                        player.cityLostTurn = self.turn

    def calculate_player_city_counts_1v1(self):
        myPlayer = self.players[self.player_index]
        otherPlayer = None
        for player in self.players:
            if not player.dead and player != myPlayer:
                otherPlayer = player

        expectCityBonus = self.turn % 2 == 0
        expectArmyBonus = self.turn % 50 == 0
        if expectArmyBonus or not expectCityBonus:
            logging.info("do nothing, we can't calculate cities on a non-even turn, or on army bonus turns!")
            return
        # if player.cityCount < cityCounts[i]:
        #	player.cityCount = cityCounts[i]
        #	player.cityGainedTurn = self.turn
        # if player.cityCount > cityCounts[i] and cityCounts[i] > 0:
        #	player.cityCount = cityCounts[i]
        #	player.cityLostTurn = self.turn
        expectedPlayerDelta = 0
        if expectCityBonus:
            # +1 for general bonus
            expectedPlayerDelta += myPlayer.cityCount

        expectedEnemyDelta = 0

        lastScores = self.scoreHistory[1]
        if lastScores is None:
            logging.info("no last scores?????")
            return
        logging.info(f"myPlayer score {myPlayer.score}, lastScores myPlayer total {lastScores[myPlayer.index].total}")
        actualPlayerDelta = myPlayer.score - lastScores[myPlayer.index].total
        logging.info(
            f'otherPlayer score {otherPlayer.score}, lastScores otherPlayer total {lastScores[otherPlayer.index].total}')

        actualEnemyDelta = otherPlayer.score - lastScores[otherPlayer.index].total

        # in a 1v1, if we lost army, then opponent also lost equal army (unless we just took a neutral tile)
        # this means we can still calculate city counts, even when fights are ongoing and both players are losing army
        # so we get the amount of unexpected delta on our player, and add that to actual opponent delta, and get the opponents city count
        fightDelta = expectedPlayerDelta - actualPlayerDelta
        realEnemyCities = actualEnemyDelta + fightDelta - expectedEnemyDelta
        if realEnemyCities <= -30:
            # then opp just took a neutral city
            otherPlayer.cityCount += 1
            logging.info("set otherPlayer cityCount += 1 to {} because it appears he just took a city.")
        elif realEnemyCities >= 30 and actualPlayerDelta < -30:
            # then our player just took a neutral city, noop
            logging.info(
                "myPlayer just took a city? ignoring realEnemyCities this turn, realEnemyCities >= 38 and actualPlayerDelta < -30")
        else:
            otherPlayer.cityCount = realEnemyCities
            logging.info(
                "set otherPlayer cityCount to {}. expectedPlayerDelta {}, actualPlayerDelta {}, expectedEnemyDelta {}, actualEnemyDelta {}, fightDelta {}, realEnemyCities {}".format(
                    otherPlayer.cityCount, expectedPlayerDelta, actualPlayerDelta, expectedEnemyDelta, actualEnemyDelta,
                    fightDelta, realEnemyCities))

    def handle_player_capture(self, text):
        capturer, capturee = text.split(" captured ")
        capturee = capturee.rstrip('.')

        # print("\n\n    ~~~~~~~~~\nPlayer captured: {} by {}\n    ~~~~~~~~~\n".format(capturer, capturee))
        capturerIdx = self.get_id_from_username(capturer)
        captureeIdx = self.get_id_from_username(capturee)
        for handler in self.notify_player_captures:
            handler(captureeIdx, capturerIdx)
        print("\n\n    ~~~~~~~~~\nPlayer captured: {} ({}) by {} ({})\n    ~~~~~~~~~\n".format(capturee, captureeIdx,
                                                                                               capturer, capturerIdx))

        if capturerIdx == self.player_index:
            # ignore, player was us, our tiles will update
            return
        if captureeIdx >= 0:
            capturedGen = self.generals[captureeIdx]
            if capturedGen is not None:
                capturedGen.isGeneral = False
                capturedGen.isCity = True
                for eventHandler in self.notify_city_found:
                    eventHandler(capturedGen)
            self.generals[captureeIdx] = None
            capturingPlayer = self.players[capturerIdx]
            for x in range(self.cols):
                for y in range(self.rows):
                    tile = self.grid[y][x]
                    if tile.player == captureeIdx:
                        tile.discoveredAsNeutral = True
                        tile.update(self, tile.tile, tile.army // 2, overridePlayer=capturerIdx)
                        for eventHandler in self.notify_tile_deltas:
                            eventHandler(tile)
                        if tile.isCity and not tile in capturingPlayer.cities:
                            capturingPlayer.cities.append(tile)
                        for eventHandler in self.notify_tile_captures:
                            eventHandler(tile)

    def get_id_from_username(self, username):
        for i, curName in enumerate(self.usernames):
            if username == curName:
                return i
        return -1

    def update_turn(self, turn: int):
        self.turn = turn
        self.army_moved_grid = [[False for x in range(self.cols)] for y in range(self.rows)]

    def update_scores(self, scores: typing.List[Score]):
        self.scores = scores

    # Emulates a tile update event from the server. Changes player tile ownership, or mountain to city, etc, and fires events
    def update_visible_tile(self, x: int, y: int, tile_type: int, tile_army: int, is_city: bool, is_general: bool):
        """
        Call this AFTER calling map.update_turn
        ONLY call this once per turn per tile, or deltas will be messed up

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
        self.army_moved_grid[y][x] = curTile.update(self, tile_type, tile_army, is_city, is_general)
        if curTile.delta.oldOwner != curTile.delta.newOwner:
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
            for eventHandler in self.notify_tile_revealed:
                eventHandler(curTile)
        if wasGeneral != curTile.isGeneral:
            for eventHandler in self.notify_general_revealed:
                eventHandler(curTile)
            self.generals[curTile.player] = curTile


    # expects _applyUpdateDiff to have been run to update the hidden grid info first
    # expects update_turn() to have been called with the new turn already.
    # expects update_visible_tile to have been called already for all tiles with updates
    # expects scores to have been recreated from latest data
    def update(self):
        for player in self.players:
            if player is not None:
                player.cities = []
                player.tiles = []

        if self.complete and self.result == False:  # Game Over - Ignore Empty Board Updates
            return self

        for i in range(len(self.scoreHistory) - 1, 0, -1):
            self.scoreHistory[i] = self.scoreHistory[i - 1]
        self.scoreHistory[0] = self.scores

        # Make assumptions about unseen tiles
        for x in range(self.cols):
            for y in range(self.rows):
                curTile = self.grid[y][x]

                # logging.info(f'MAP: {self.turn} : {str(curTile)}, {curTile.army}')
                if curTile.isCity and curTile.player != -1:
                    self.players[curTile.player].cities.append(curTile)
                if self.army_moved_grid[y][x]:
                    # look for candidate tiles that army may have come from
                    bestCandTile = None
                    bestCandValue = -1
                    if x - 1 >= 0:  # examine left
                        candidateTile = self.grid[y][x - 1]
                        candValue = evaluateTileDiffs(curTile, candidateTile)
                        if candValue > bestCandValue:
                            bestCandValue = candValue
                            bestCandTile = candidateTile
                    if x + 1 < self.cols:  # examine right
                        candidateTile = self.grid[y][x + 1]
                        candValue = evaluateTileDiffs(curTile, candidateTile)
                        if candValue > bestCandValue:
                            bestCandValue = candValue
                            bestCandTile = candidateTile
                    if y - 1 >= 0:  # examine top
                        candidateTile = self.grid[y - 1][x]
                        candValue = evaluateTileDiffs(curTile, candidateTile)
                        if candValue > bestCandValue:
                            bestCandValue = candValue
                            bestCandTile = candidateTile
                    if y + 1 < self.rows:  # examine bottom
                        candidateTile = self.grid[y + 1][x]
                        candValue = evaluateTileDiffs(curTile, candidateTile)
                        if candValue > bestCandValue:
                            bestCandValue = candValue
                            bestCandTile = candidateTile

                    if bestCandTile is not None:
                        self.army_moved_grid[bestCandTile.y][bestCandTile.x] = False
                        if bestCandValue >= 100:
                            # only say the army is completely covered if the confidence was high, otherwise we can have two armies move here from diff players
                            self.army_moved_grid[y][x] = False
                        if curTile.player == -1:
                            curTile.player = bestCandTile.player
                        curTile.delta.fromTile = bestCandTile
                        bestCandTile.delta.toTile = curTile
                if (not curTile.visible and (
                        curTile.isCity or curTile.isGeneral) and curTile.player >= 0 and self.turn % 2 == 0):
                    curTile.army += 1
                if not curTile.visible and curTile.player >= 0 and self.turn % 50 == 0:
                    curTile.army += 1
                if curTile.player >= 0:
                    self.players[curTile.player].tiles.append(curTile)

        self.update_reachable()

        # we know our players city count + his general because we can see all our own cities
        self.players[self.player_index].cityCount = len(self.players[self.player_index].cities) + 1
        self._update_player_information()
        return self

    def updateResult(self, result):
        self.complete = True
        self.result = result == "game_won"
        return self


    def init_grid_movable(self):
        for x in range(self.cols):
            for y in range(self.rows):
                tile = self.grid[y][x]
                if len(tile.adjacents) != 0:
                    continue

                movableTile = self.GetTile(x - 1, y)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                movableTile = self.GetTile(x + 1, y)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                movableTile = self.GetTile(x, y - 1)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                movableTile = self.GetTile(x, y + 1)
                if movableTile is not None and movableTile not in tile.movable:
                    tile.adjacents.append(movableTile)
                    tile.movable.append(movableTile)
                adjTile = self.GetTile(x - 1, y - 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)
                adjTile = self.GetTile(x + 1, y - 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)
                adjTile = self.GetTile(x - 1, y + 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)
                adjTile = self.GetTile(x + 1, y + 1)
                if adjTile is not None and adjTile not in tile.adjacents:
                    tile.adjacents.append(adjTile)

                if tile.isGeneral:
                    self.generals[tile.player] = tile

        self.update_reachable()

    def update_reachable(self):
        pathableTiles = set()
        reachableTiles = set()

        queue = []

        for gen in self.generals:
            if gen is not None:
                queue.append(gen)
                self.players[gen.player].general = gen

        while len(queue) > 0:
            tile = queue.pop(0)
            isNeutCity = tile.isCity and tile.isNeutral
            tileIsPathable = not tile.isNotPathable
            if tile not in pathableTiles and tileIsPathable and not isNeutCity:
                pathableTiles.add(tile)
                for movable in tile.movable:
                    queue.append(movable)
                    reachableTiles.add(movable)

        self.pathableTiles = pathableTiles
        self.reachableTiles = reachableTiles


# Actual live server map that interacts with the crazy array patch diffs.
class Map(MapBase):
    def __init__(self, start_data, data):
        # Start Data

        self.stars: typing.List[int] = [0 for x in range(8)]
        self._start_data = start_data
        replay_url = _REPLAY_URLS["na"] + start_data['replay_id']  # String Replay URL # TODO: Use Client Region

        # First Game Data, sets up all the private server-array-style-tile-caches
        self._apply_server_patch(data)

        map_grid_y_x: typing.List[typing.List[Tile]] = [[Tile(x, y) for x in range(self.cols)] for y in range(self.rows)]
        teams = None
        if 'teams' in start_data:
            teams = start_data['teams']

        super().__init__(start_data['playerIndex'], teams, start_data['usernames'], data['turn'], map_grid_y_x, replay_url, start_data['replay_id'])

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

    def _get_raw_scores_from_data(self, data):
        scores = {s['i']: s for s in data['scores']}
        scores = [scores[i] for i in range(len(scores))]

        return scores

    def _apply_server_patch(self, data):
        if not '_map_private' in dir(self):
            self._map_private = []
            self._cities_private = []
        # TODO update map prediction
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


class MapMatrix:
    def __init__(self, map: MapBase, initVal=False):
        self.init_val = initVal
        self.grid = new_value_matrix(map, initVal)

    def add(self, item: Tile, value=True):
        self.grid[item.x][item.y] = value

    def __setitem__(self, key: Tile, item):
        self.grid[key.x][key.y] = item

    def __getitem__(self, key: Tile):
        val = self.grid[key.x][key.y]
        return val

    def __repr__(self):
        return repr(self.grid)

    def values(self):
        all = []
        for row in self.grid:
            for item in row:
                if item != self.init_val:
                    all.append(item)
        return all

    def __delitem__(self, key: Tile):
        self.grid[key.x][key.y] = self.init_val

    def __contains__(self, item):
        return self.grid[item.x][item.y] != self.init_val


def new_map_matrix(map, initialValueXYFunc):
    return [[initialValueXYFunc(x, y) for y in range(map.rows)] for x in range(map.cols)]


def new_tile_matrix(map, initialValueTileFunc):
    return [[initialValueTileFunc(map.grid[y][x]) for y in range(map.rows)] for x in range(map.cols)]


def new_value_matrix(map, initValue) -> typing.List[typing.List[int]]:
    return [[initValue] * map.rows for _ in range(map.cols)]


def evaluateTileDiffs(tile: Tile, candidateTile: Tile):
    # both visible
    if tile.visible:
        if candidateTile.visible:
            return evaluateDualVisibleTileDiffs(tile, candidateTile)
        else:
            return evaluateMoveFromFog(tile, candidateTile)
    else:
        return evaluateIslandFogMove(tile, candidateTile)


def evaluateDualVisibleTileDiffs(tile, candidateTile):
    if tile.delta.oldOwner != tile.delta.newOwner:
        if tile.delta != 0:
            deltasMatch = tile.delta.armyDelta == candidateTile.delta.armyDelta
            if deltasMatch:
                return 1000

        else:
            # something fishy happened here because by getting into this method, we KNOW the tile was interacted with
            # but if its delta is zero then it means two armies collided. Just look for a candidate tile with a delta, then.

            if candidateTile.delta.armyDelta < 0 and candidateTile.player == tile.delta.newOwner:
                logging.info(f'evaluateDualVisibleTileDiffs {str(tile)} capped by {str(candidateTile)} despite collision, as determined by tile delta player match')
                return 1000

            if candidateTile.delta.armyDelta < 0:
                # then may have collided without capping it
                return 75
    elif (candidateTile.delta.oldOwner == candidateTile.delta.newOwner
            and candidateTile.player == tile.player):
        return evaluateSameOwnerMoves(tile, candidateTile)
    # elif (tile.delta.oldOwner == -1
    #         and candidateTile.delta.oldOwner == candidateTile.delta.newOwner
    #         and candidateTile.player == tile.player):
    #     return evaluateSameOwnerMoves(tile, candidateTile)
    # return evaluateSameOwnerMoves(tile, candidateTile)
    return -100


def evaluateMoveFromFog(tile, candidateTile):
    """returns an int where negative means definitely not and positive int means probably"""
    # if tile.delta.oldOwner == tile.delta.newOwner:
    #     return -100
    if candidateTile.visible:
        return -100

    if tile.delta.armyDelta == 0:
        # then we're in this weird situation where we KNOW the tile was captured or something but armies collided in the process
        # if ONLY one tile adjacent is fog, then MUST have come from there, or we'd have already picked a visible tile with a delta
        if candidateTile.army > 0:
            logging.info(f'candidateTile.army > 0 '
                         f'{candidateTile.x},{candidateTile.y}({candidateTile.delta.armyDelta})'
                         f'->{tile.x},{tile.y}({tile.delta.armyDelta})')
            return 10

        logging.info(f'tile.delta.armyDelta == 0 '
                     f'{candidateTile.x},{candidateTile.y}({candidateTile.delta.armyDelta})'
                     f'->{tile.x},{tile.y}({tile.delta.armyDelta})')
        return -100

    candidateDelta = candidateTile.army + tile.delta.armyDelta
    if candidateDelta == 0:
        logging.info(f'(evaluateMoveFromFog) candidateDelta == 0 '
                     f'{candidateTile.x},{candidateTile.y}({candidateTile.delta.armyDelta})'
                     f'->{tile.x},{tile.y}({tile.delta.armyDelta})')
        # return 40
        return 100

    halfMoveAmount = (candidateTile.army // 2)
    halfDelta = halfMoveAmount + tile.delta.armyDelta
    if halfMoveAmount > 0 and halfDelta == 0:
        logging.info(f'halfMoveAmount > 0 and halfDelta == 0 '
                     f'{candidateTile.x},{candidateTile.y}({candidateTile.delta.armyDelta})'
                     f'->{tile.x},{tile.y}({tile.delta.armyDelta})')
        return 35

    return -100


def evaluateIslandFogMove(tile, candidateTile):
    # print(str(tile.army) + " : " + str(candidateTile.army))
    if candidateTile.visible and tile.army + candidateTile.delta.armyDelta < -1 and candidateTile.player != -1:
        tile.player = candidateTile.player
        tile.delta.newOwner = candidateTile.player
        tile.army = 0 - candidateTile.delta.armyDelta - tile.army
        candidateTile.army = 1
        logging.info(" (islandFog 1) tile {} army to {}".format(tile.toString(), tile.army))
        logging.info(" (islandFog 1) candTile {} army to 1".format(candidateTile.toString()))
        return 40
    if tile.army - candidateTile.army < -1 and candidateTile.player != -1:
        tile.player = candidateTile.player
        tile.delta.newOwner = candidateTile.player
        tile.army = candidateTile.army - tile.army - 1
        candidateTile.army = 1
        logging.info(" (islandFog 2) tile {} army to {}".format(tile.toString(), tile.army))
        logging.info(" (islandFog 2) candTile {} army to 1".format(candidateTile.toString()))
        return 30
    return -100


def evaluateSameOwnerMoves(tile, candidateTile):
    if tile.delta.armyDelta > 0:
        delta = tile.delta.armyDelta + candidateTile.delta.armyDelta
        if delta == 0:
            logging.info(f'same owner tile delta evaludation of '
                         f'{candidateTile.x},{candidateTile.y}({candidateTile.delta.armyDelta})'
                         f'->{tile.x},{tile.y}({tile.delta.armyDelta}) '
                         f'resulted in a delta of {delta}, obviously was correct movement')
            return 100
        if candidateTile.delta.armyDelta < 0:
            logging.info(f'same owner tile delta evaluation of '
                         f'{candidateTile.x},{candidateTile.y}({candidateTile.delta.armyDelta})'
                         f'->{tile.x},{tile.y}({tile.delta.armyDelta}) '
                         f'resulted in a delta of {delta}')
            return 75
    return -100


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
