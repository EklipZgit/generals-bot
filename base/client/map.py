'''
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Map: Objects for representing Generals IO Map and Tiles
'''
import json
import logging
import typing
from collections import deque

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
        self.cities = []
        self.general = None
        self.index = player_index
        self.stars = 0
        self.score = 0
        self.tiles = []
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
        self.fromTile = None
        self.toTile = None


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

    @property
    def player(self) -> int:
        """int player index"""
        return self._player

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
    def isObstacle(self) -> bool:
        """True if mountain, undiscovered obstacle, or discovered neutral city"""
        return self.isMountain or self.isUndiscoveredObstacle or (self.isCity and self.isNeutral)

    @player.setter
    def player(self, value):
        if value >= 0:
            self.tile = value
        elif value == -1 and self.army == 0 and not self.isNotPathable and not self.isCity:
            self.tile = TILE_EMPTY
        self._player = value

    def __repr__(self):
        return "(%d,%d) %d (%d)" % (self.x, self.y, self.tile, self.army)

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

    def tileToString(self, tile):
        if tile == TILE_EMPTY:
            return "Empty"
        elif tile == TILE_FOG:
            return "Fog"
        elif tile == TILE_MOUNTAIN:
            return "Mountain"
        elif tile == TILE_OBSTACLE:
            return "Obstacle"
        return "Player " + str(tile)

    def __str__(self) -> str:
        return self.toString()

    def toString(self) -> str:
        return "{},{}".format(self.x, self.y)

    # returns true if an army was likely moved to this tile, false if not.
    def update(self, map, tile, army, isCity=False, isGeneral=False, overridePlayer=None) -> bool:

        # if (self.tile < 0 or tile >= 0 or (tile < TILE_MOUNTAIN and self.tile == map.player_index)): # Remember Discovered Tiles
        #	if (tile >= 0 and self.tile != tile):
        #		if (self._player != tile):
        #			self.turn_captured = map.turn
        #			self._player = tile
        #			print("Tile " + str(self.x) + "," + str(self.y) + " captured by player " + str(tile))
        #	if (self.tile != tile):
        #		print("Tile " + str(self.x) + "," + str(self.y) + " from " + self.tileToString(self.tile) + " to " + self.tileToString(tile))
        #		self.tile = tile
        #		if (tile == TILE_MOUNTAIN):
        #			self.isMountain = True

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
                    armyMovedHere = True
                    self._player = -1
            elif tile == TILE_MOUNTAIN:
                self.isMountain = True
            elif tile >= 0:
                self._player = tile

            self.tile = tile

        self.delta.newOwner = self._player
        if overridePlayer is not None:
            self.delta.newOwner = overridePlayer
            self._player = overridePlayer

        if (army == 0 and self.visible) or army > 0 and (
                self.army != army or self.delta.oldOwner != self.delta.newOwner):  # Remember Discovered Armies
            if self.army == 0 or self.army - army > 1 or self.army - army < -1:
                armyMovedHere = True
            oldArmy = self.army
            # logging.info("assigning tile {} with oldArmy {} new army {}?".format(self.toString(), oldArmy, army))
            self.army = army
            if self.delta.oldOwner != self.delta.newOwner:
                self.delta.armyDelta = 0 - (self.army + oldArmy)
            else:
                self.delta.armyDelta = self.army - oldArmy

        if isCity:
            self.isCity = True
            self.isGeneral = False
            # if self in map.cities:
            #	map.cities.remove(self)
            # map.cities.append(self)
            if not self in map.cities:
                map.cities.append(self)

            # playerObj = map.players[self._player]

            # if not self in playerObj.cities:
            #	playerObj.cities.append(self)

            if self in map.generals:
                map.generals[self._general_index] = None
        elif isGeneral:
            playerObj = map.players[self._player]
            playerObj.general = self
            self.isGeneral = True
            map.generals[tile] = self
            self._general_index = self.tile

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
                 replay_url: str
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

        self.scores: typing.List[Score] = [Score(x, 0, 0, False) for x in range(8)]  # List of Player Scores
        self.complete = False  # Boolean Game Complete
        self.result = False  # Boolean Game Result (True = Won)
        self.scoreHistory: typing.List[typing.Union[None, typing.List[Score]]] = [None for i in range(25)]
        self.remainingPlayers = 0

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
        curTile = self.grid[y][x]
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
                # WHY ARE WE DOING THIS....?
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
                if curTile.isCity and curTile.player != -1:
                    self.players[curTile.player].cities.append(curTile)
                if self.army_moved_grid[y][x]:
                    # look for candidate tiles that army may have come from
                    bestCandTile = None
                    bestCandValue = -1
                    if x - 1 > 0:  # examine left
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
                    if y - 1 > 0:  # examine top
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

        while len(queue) > 0:
            tile = queue.pop(0)
            if tile not in pathableTiles and not tile.isUndiscoveredObstacle and not tile.isMountain:
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

        super().__init__(start_data['playerIndex'], teams, start_data['usernames'], data['turn'], map_grid_y_x, replay_url)

        self.apply_server_update(data)

        # TODO get scores to base class somehow
        #super().up
        # self.scores = self._getScores(data)  # List of Player Scores

    def apply_server_update(self, data):
        self._apply_server_patch(data)

        self.update_turn(data['turn'])

        self.update_scores(Score.from_server_scores(self._get_raw_scores_from_data(data)))

        for x in range(self.cols):  # Update Each Tile
            for y in range(self.rows):
                # if (self._tile_grid[y][x] != oldTiles[y][x]):
                # tile changed ownership or visibility
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


def evaluateTileDiffs(tile, candidateTile):
    # both visible
    if tile.visible and candidateTile.visible:
        return evaluateDualVisibleTileDiffs(tile, candidateTile)
    if tile.visible and not candidateTile.visible:
        return evaluateMoveFromFog(tile, candidateTile)
    if not tile.visible:
        # print("evaluating fog island. friendlyCaptured: " + str(tile.delta.friendlyCaptured))
        return evaluateIslandFogMove(tile, candidateTile)
    return -100


def evaluateDualVisibleTileDiffs(tile, candidateTile):
    if (
            tile.delta.oldOwner == tile.delta.newOwner and candidateTile.delta.oldOwner == candidateTile.delta.newOwner and candidateTile.player == tile.player):
        return evaluateSameOwnerMoves(tile, candidateTile)
    if (
            tile.delta.oldOwner == -1 and candidateTile.delta.oldOwner == candidateTile.delta.newOwner and candidateTile.player == tile.player):
        return evaluateSameOwnerMoves(tile, candidateTile)
    # return evaluateSameOwnerMoves(tile, candidateTile)
    return -100


def evaluateMoveFromFog(tile, candidateTile):
    if tile.delta.oldOwner == tile.delta.newOwner:
        return -100
    candidateDelta = candidateTile.army + tile.delta.armyDelta
    if candidateDelta >= 0 and candidateDelta <= 2:
        candidateTile.army = 1
        logging.info(
            " (evaluateMoveFromFog) candidateTile {} army to {}".format(candidateTile.toString(), candidateTile.army))
        return 100
    halfDelta = (candidateTile.army / 2) + tile.delta.armyDelta
    if halfDelta >= 0 and halfDelta <= 2:
        return 50
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
        return 50
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
            return 100
        if delta <= 2 and delta >= 0:
            return 50
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
