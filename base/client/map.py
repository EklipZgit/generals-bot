"""
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Map: Objects for representing Generals IO Map and Tiles
"""
from __future__ import annotations

import logging
import random
import typing
import uuid
from collections import deque

import BotLogging
import DebugHelper

ENABLE_DEBUG_ASSERTS = False

LEFT_GAME_FFA_CAPTURE_LIMIT = 50
"""How many turns after an FFA player disconnects that you can capture their gen."""

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
        self.index: int = player_index
        self.stars = 0
        self.score: int = 0

        self.scoreDelta: int = 0
        """The player score delta since last move."""

        self.tileDelta: int = 0
        """The player tile delta since last move."""

        self.unexplainedTileDelta: int = 0
        """The tile delta unexplained by known moves."""

        self.tiles: typing.List[Tile] = []
        self.tileCount: int = 0
        self.standingArmy: int = 0
        self.cityCount: int = 1
        self.cityLostTurn: int = 0
        self.cityGainedTurn: int = 0
        self.delta25tiles: int = 0
        self.delta25score: int = 0
        self.actualScoreDelta: int = 0
        self.expectedScoreDelta: int = 0

        self.fighting_with_player_history: typing.List[int] = []

        self.fighting_with_player: int = -1
        """
        If player score deltas show players fighting with each other on this turn, then this will be set. 
        If multiple players are found that all match deltas, then tiebreaks are performed based on recent historical
        fights. If the player is clearly fighting with someone but the deltas dont line up because a third party is
        involved, then this value will be unmodified from previous turn, usually continuing to indicate the last player
        they were already fighting with.
        """

        self.last_move: typing.Tuple[Tile | None, Tile | None] | None = None
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
        return f'p{self.index}{"(dead)" if self.dead else ""}: tiles {self.tileCount}, standingArmy {self.standingArmy}, general {str(self.general)}'


class TileDelta(object):
    def __init__(self):
        # Public Properties
        self.oldArmy: int = 0
        self.oldOwner = -1
        self.newOwner = -1
        self.gainedSight = False
        """True on turns where the player JUST gained sight of the tile, not when the tile was already visible the turn before."""

        self.lostSight = False
        """True on turns where the player JUST lost sight of the tile, and no others."""

        self.discovered: bool = False
        """ True on the turn a tile is discovered and ONLY that turn."""

        self.imperfectArmyDelta = False
        """True when we either just gained vision of the tile or dont have vision of the tile. Means armyDelta can be ignored and fudged."""

        self.friendlyCaptured = False
        """ true when this was a friendly tile and was captured """

        self.armyDelta = 0
        """
        UNEXPLAINED BY GAME ENGINE army delta. So this will be 0 for a tile that was not interacted with whether army bonus, 
        city bonus, general bonus, etc. If it matches what would be expected on a turn update, then it is 0.
        
        Positive means friendly army was moved ON to this tile (or army bonuses happened), 
        negative means army moved off or was attacked for not full damage OR was captured by opp.
        This includes city/turn25 army bonuses, so should ALWAYS be 0 UNLESS a player interacted 
        with the tile (or the tile was just discovered?). A capped neutral tile will have a negative army delta.
        """

        self.unexplainedDelta = 0
        """
        UNEXPLAINED BY MOVEMENT PREDICTION. AS WE DETERMINE MOVEMENT THIS WILL BECOME 0 AS DELTA.fromTile/toTile GET UPDATED.
        """

        self.fromTile: Tile | None = None
        """If this tile is suspected to have been the target of a move last turn, this is the tile the map algo thinks the move is from."""

        self.toTile: Tile | None = None
        """If this tile is suspected to have had its army moved, this is the tile the map algo thinks it moved to."""

        self.armyMovedHere: bool = False
        """Indicates whether the tile update thinks an army MAY have moved here. Becomes FALSE once toTile/fromTile are populated."""

        self.expectedDelta: int = 0
        """The EXPECTED army delta of the tile, this turn."""

    def __str__(self):
        pieces = [f'{self.armyDelta:+d}']
        if self.oldOwner != self.newOwner:
            pieces.append(f'p{self.oldOwner}->p{self.newOwner}')
        if self.fromTile:
            pieces.append(f'<- {repr(self.fromTile)}')
        if self.toTile:
            pieces.append(f'-> {repr(self.toTile)}')
        if self.armyMovedHere:
            pieces.append(f'<-?')
        return ' '.join(pieces)

    def __repr__(self):
        return str(self)

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
        # self._army: int = army

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

        self.lastMovedTurn: int = -1
        """Turn the tile last had an unexpected delta on it"""

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
        return self._player == -1

    @property
    def isUndiscoveredObstacle(self) -> bool:
        """True if not discovered and is a map obstacle/mountain"""
        return self.tile == TILE_OBSTACLE and not self.discovered and not self.isCity

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
        # TODO why is any of this tile setter shit here at all?
        if value >= 0 and self.visible:
            self.tile = value
        elif value == -1 and self.army == 0 and not self.isNotPathable and not self.isCity and not self.isMountain:
            self.tile = TILE_EMPTY # this whole thing seems wrong, needs to be updated carefully with tests as the delta logic seems to rely on it...
        self._player = value

    # @property
    # def army(self) -> int:
    #     """int army val for debugging"""
    #     return self._army
    #
    # @army.setter
    # def army(self, value):
    #     self._army = value

    @staticmethod
    def convert_player_to_char(player: int):
        match player:
            case -1:
                return 'N'
            case 0:
                return 'a'
            case 1:
                return 'b'
            case 2:
                return 'c'
            case 3:
                return 'd'
            case 4:
                return 'e'
            case 5:
                return 'f'
            case 6:
                return 'g'
            case 7:
                return 'h'
            case 8:
                return 'i'
            case 9:
                return 'j'
            case 10:
                return 'k'
            case 11:
                return 'l'
            case 12:
                return 'm'
            case 13:
                return 'n'
            case 14:
                return 'o'
            case 15:
                return 'p'

    def __repr__(self):
        vRep = self.get_value_representation()

        delta = ''
        if self.delta.armyDelta != 0 or self.delta.unexplainedDelta != 0:
            delta = f' {self.delta.armyDelta}|{self.delta.unexplainedDelta}'

        return f"({self.x:d},{self.y:d}) {vRep}{delta}"

    def get_value_representation(self) -> str:
        outputToJoin = []
        if self.player >= 0:
            playerChar = Tile.convert_player_to_char(self.player)
            outputToJoin.append(playerChar)
        if self.isCity:
            outputToJoin.append('C')
        if self.isMountain or (not self.visible and self.isNotPathable):
            outputToJoin.append('M')
        if self.isGeneral:
            outputToJoin.append('G')
        if self.army != 0 or self.player >= 0:
            if self.player == -1 and not self.isCity:
                outputToJoin.append('N')
            armyStr = str(self.army)
            outputToJoin.append(armyStr)

        if self.discovered and not self.visible:
            outputToJoin.append('D')

        return ''.join(outputToJoin)


    """def __eq__(self, other):
            return (other != None and self.x==other.x and self.y==other.y)"""

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

    def was_not_visible_last_turn(self):
        return self.delta.gainedSight or (not self.visible and not self.delta.lostSight)

    def was_visible_last_turn(self):
        return self.delta.lostSight or (self.visible and not self.delta.gainedSight)

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
        self.delta: TileDelta = TileDelta()
        self.delta.oldArmy = self.army
        if not self.visible:
            self.delta.imperfectArmyDelta = True
        if tile >= TILE_MOUNTAIN:
            if not self.discovered:
                self.discovered = True
                self.delta.discovered = True
            self.lastSeen = map.turn
            if not self.visible:
                self.delta.gainedSight = True
                self.visible = True

        armyMovedHere = False

        self.delta.oldOwner = self._player

        if self.tile != tile:  # tile changed
            if tile < TILE_MOUNTAIN and self.discovered:  # lost sight of tile.
                if self.visible:
                    self.delta.lostSight = True
                self.visible = False
                self.lastSeen = map.turn - 1

                if self._player == map.player_index or self._player in map.teammates:
                    # we lost the tile
                    # I think this is handled by the Fog Island handler during map update...?
                    self.delta.friendlyCaptured = True
                    logging.info(f'tile captured, losing vision, army moved here true for {str(self)}')
                    armyMovedHere = True
                    self._player = -1
                elif self._player >= 0 and self.army > 1:
                    # we lost SIGHT of enemy tile, IF this tile has positive army, then army could have come from here TO another tile.
                    logging.info(f'enemy tile adjacent to vision lost was lost, army moved here true for {str(self)}')  # TODO
                    # armyMovedHere = True
            elif tile >= TILE_EMPTY:
                self._player = tile

            self.tile = tile

        if tile == TILE_MOUNTAIN:
            if not self.isMountain:
                for movableTile in self.movable:
                    if self in movableTile.movable:
                        movableTile.movable.remove(self)

                self.isMountain = True

            if self.player != -1 or self.isCity or self.army != 0:
                # mis-predicted city.
                self.isCity = False
                self.army = 0
                self.player = -1

        # can only 'expect' army deltas for tiles we can see. Visible is already calculated above at this point.
        # WAS
        # if self.visible and not self.delta.discovered:
        if tile >= TILE_EMPTY:
            expectedDelta: int = 0
            if (self.isCity or self.isGeneral) and self.player >= 0 and map.is_city_bonus_turn:
                expectedDelta += 1

            if self.player >= 0 and map.is_army_bonus_turn:
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

        if isCity and not self.isCity:
            self.isCity = True
            self.isGeneral = False

        elif isGeneral:
            playerObj = map.players[self._player]
            playerObj.general = self
            self.isGeneral = True
            # TODO remove, this should NOT happen here
            map.generals[tile] = self
            self._general_index = self.tile

        if self.delta.oldOwner != self.delta.newOwner:
            # TODO  and not self.delta.gainedSight ?
            logging.debug(f'oldOwner != newOwner for {str(self)}')
            armyMovedHere = True

        # if self.delta.oldOwner == self.delta.newOwner and self.delta.armyDelta == 0:
        #     armyMovedHere = False

        if tile == TILE_MOUNTAIN or (tile == TILE_EMPTY and isCity and self.delta.gainedSight):
            armyMovedHere = False
            if tile == TILE_MOUNTAIN or army > 38:
                self.delta.imperfectArmyDelta = False
                self.delta.armyDelta = 0
                self.delta.unexplainedDelta = 0

        self.delta.armyMovedHere = armyMovedHere

        if armyMovedHere:
            logging.debug(f'armyMovedHere True for {str(self)} (expected delta was {self.delta.expectedDelta}, actual was {self.delta.armyDelta})')
            self.lastMovedTurn = map.turn

        if not self.visible:
            self.delta.imperfectArmyDelta = True

        self.delta.unexplainedDelta = self.delta.armyDelta

        return armyMovedHere

    def set_disconnected_neutral(self):
        if self.visible:
            raise AssertionError(f'Trying to set visible disconnected neutral tile, when that should have been handled by map update already...? {str(self)}')

        self._player = -1
        self.tile = TILE_FOG

        if not self.discovered and self.isCity:
            self.tile = TILE_OBSTACLE
            self.isCity = False
            self.army = 0

        if self.isGeneral:
            self.isGeneral = False
            self.isCity = True

    def reset_wrong_undiscovered_fog_guess(self):
        """
        DO NOT call this for discovered-neutral-cities that were fog-guessed as captured, or they will be 'undiscovered' again.
        Changes fog cities back to undiscovered mountains.
        Changes player-capped-tiles back to undiscovered neutrals.
        """
        if self.isCity:
            self.tile = TILE_OBSTACLE
            self.isCity = False
        else:
            self.tile = TILE_FOG
        self.army = 0
        self._player = -1

    @classmethod
    def get_move_half_amount(cls, army: int) -> int:
        """This is the amount of army that will leave the tile, not the amount that will be left on the tile."""
        return army // 2


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
        # self.USE_OLD_MOVEMENT_DETECTION = True
        self.last_player_index_submitted_move: typing.Tuple[Tile, Tile, bool] | None = None
        self.player_index: int = player_index  # Integer Player Index
        # TODO TEAMMATE
        self.is_2v2: bool = False
        self.teammates = set()

        uniqueTeams = set()
        if teams is not None:
            for player, team in enumerate(teams):
                uniqueTeams.add(team)
                if team == teams[self.player_index] and player != self.player_index:
                    self.teammates.add(player)
            if len(uniqueTeams) == 2:
                self.is_2v2 = True

        self.teams: typing.List[int] | None = teams

        self.usernames: typing.List[str] = user_names  # List of String Usernames
        self.players: typing.List[Player] = [Player(x) for x in range(len(self.usernames))]
        self._teams = MapBase.get_teams_array(self)
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

        self.scoreHistory: typing.List[typing.Union[None, typing.List[Score]]] = [None for i in range(50)]
        """Last 50 turns worth of score histories, by player."""

        self.remainingPlayers = 0

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f'p{self.player_index} t{self.turn}'

    @property
    def turn(self) -> int:
        return self._turn

    @turn.setter
    def turn(self, val: int):
        if val & 1 == 0:
            self.is_city_bonus_turn = True
            if val % 50 == 0:
                self.is_army_bonus_turn = True
            else:
                self.is_army_bonus_turn = False
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
                    if not player.leftGame:
                        player.leftGame = True
                        player.leftGameTurn = self.turn
                    # don't immediately set 'dead' so that we keep attacking disconnected player
                    if self.scores[i].tiles == 0:
                        player.dead = True
                        if len(player.tiles) > 0:
                            for tile in player.tiles:
                                if not tile.visible:
                                    tile.set_disconnected_neutral()

                else:
                    self.remainingPlayers += 1

        self.calculate_player_deltas()

        if self.remainingPlayers > 2 and self.is_city_bonus_turn and not self.is_2v2:
            for i, player in enumerate(self.players):
                if not player.dead and player.index != self.player_index:
                    if player.cityCount < cityCounts[i]:
                        player.cityCount = cityCounts[i]
                        player.cityGainedTurn = self.turn
                    if player.cityCount > cityCounts[i] and cityCounts[i] > 0:
                        player.cityCount = cityCounts[i]
                        player.cityLostTurn = self.turn

    def handle_player_capture_text(self, text):
        capturer, capturee = text.split(" captured ")
        capturee = capturee[:-1]

        capturerIdx = self.get_id_from_username(capturer)
        captureeIdx = self.get_id_from_username(capturee)

        self.handle_player_capture(capturerIdx, captureeIdx)

    def handle_player_capture(self, capturerIdx: int, captureeIdx: int):
        if captureeIdx == self.player_index:
            logging.info(
                f"\n\n    ~~~~~~~~~\nWE WERE CAPTURED BY {self.usernames[capturerIdx]}, IGNORING CAPTURE: {self.usernames[captureeIdx]} ({captureeIdx}) by {self.usernames[capturerIdx]} ({capturerIdx})\n    ~~~~~~~~~\n")
            return

        if self.player_index == capturerIdx or capturerIdx in self.teammates:
            logging.info(
                f"\n\n    ~~~~~~~~~\nWE CAPTURED {captureeIdx}, NUKING UNDISCOVEREDS: {self.usernames[captureeIdx]} ({captureeIdx}) by {self.usernames[capturerIdx]} ({capturerIdx})\n    ~~~~~~~~~\n")
            for tile in self.get_all_tiles():
                if tile.player == captureeIdx and not tile.visible:
                    tile.reset_wrong_undiscovered_fog_guess()

        logging.info(
            f"\n\n    ~~~~~~~~~\nPlayer captured: {self.usernames[captureeIdx]} ({captureeIdx}) by {self.usernames[capturerIdx]} ({capturerIdx})\n    ~~~~~~~~~\n")

        if captureeIdx < 0:
            raise AssertionError(f'what? Player captured was {captureeIdx}')

        for handler in self.notify_player_captures:
            handler(captureeIdx, capturerIdx)

        capturedGen = self.generals[captureeIdx]
        if capturedGen is not None:
            capturedGen.isGeneral = False
            capturedGen.isCity = True
            for eventHandler in self.notify_city_found:
                eventHandler(capturedGen)
        self.generals[captureeIdx] = None

        capturingPlayer = self.players[capturerIdx]
        captureePlayer = self.players[captureeIdx]
        captureePlayer.capturedBy = capturerIdx
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
            tile.tile = capturerIdx
            tile.player = capturerIdx
            if tile.isGeneral:
                tile.isGeneral = False
                tile.isCity = True

                # TODO not safe to call all these delta methods, pretty sure...
                for eventHandler in self.notify_city_found:
                    eventHandler(tile)
            else:
                tile.army = tile.army - tile.army // 2

            for eventHandler in self.notify_tile_deltas:
                eventHandler(tile)
            if tile.isCity and not tile in capturingPlayer.cities:
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

    def is_tile_friendly(self, tile: Tile) -> bool:
        if self._teams[self.player_index] == self._teams[tile.player]:
            return True
        return False

    def is_tile_enemy(self, tile: Tile) -> bool:
        if not self.is_tile_friendly(tile) and tile.player >= 0:
            return True

        return False

    # Emulates a tile update event from the server. Changes player tile ownership, or mountain to city, etc, and fires events
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
        ONLY call this once per turn per tile, or deltas will be messed up.
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
        maybeMoved = curTile.update(self, tile_type, tile_army, is_city, is_general)
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
            for eventHandler in self.notify_tile_revealed:
                eventHandler(curTile)
        if wasGeneral != curTile.isGeneral:
            for eventHandler in self.notify_general_revealed:
                eventHandler(curTile)
            if curTile.isGeneral:
                self.generals[curTile.player] = curTile
            else:
                for i, maybeNotGen in list(enumerate(self.generals)):
                    if maybeNotGen is not None and maybeNotGen.player != i:
                        maybeNotGen.isCity = True
                        maybeNotGen.isGeneral = False
                        self.generals[i] = None

    def update(self, bypassDeltas: bool = False):
        """
        Expects _applyUpdateDiff to have been run to update the hidden grid info first.
        Expects update_turn() to have been called with the new turn already.
        Expects update_visible_tile to have been called already for all tiles with updates.
        Expects scores to have been recreated from latest data.

        @param bypassDeltas: If passes, fog-city-and-army-increments will not be applied this turn, and tile-movement deltas will not be tracked.
        """
        for player in self.players:
            if player is not None:
                player.cities = []
                player.tiles = []

        if self.complete and not self.result and self.remainingPlayers > 2:  # Game Over - Ignore Empty Board Updates in FFA
            return self

        for i in range(len(self.scoreHistory) - 1, 0, -1):
            self.scoreHistory[i] = self.scoreHistory[i - 1]
        self.scoreHistory[0] = self.scores

        self._update_player_information()

        # right now all tile deltas are completely raw, as applied by the raw server update, with the exception of lost-vision-fog.

        for x in range(self.cols):
            for y in range(self.rows):
                curTile = self.grid[y][x]

                if curTile.player >= 0:
                    self.players[curTile.player].tiles.append(curTile)

                if curTile.isCity and curTile.player != -1:
                    self.players[curTile.player].cities.append(curTile)

        if not bypassDeltas:
            self.detect_movement_and_populate_unexplained_diffs()
        #
        # else:
        #
        #     if not bypassDeltas:
        #         # Check for OBVIOUS army movement, first
        #         for x in range(self.cols):
        #             for y in range(self.rows):
        #                 curTile = self.grid[y][x]
        #
        #                 maybeMovedTo = self.army_moved_grid[y][x]
        #                 if maybeMovedTo:
        #                     # look for candidate tiles that army may have come from
        #                     bestCandTile = evaluateTileDiffsVisible(curTile)
        #
        #                     if bestCandTile is not None:
        #                         byPlayer = curTile.player
        #                         if byPlayer == -1:
        #                             byPlayer = bestCandTile.player
        #                         self.set_tile_moved(curTile, bestCandTile, byPlayer=byPlayer)
        #
        #         # Make assumptions about unseen tiles
        #         for x in range(self.cols):
        #             for y in range(self.rows):
        #                 curTile = self.grid[y][x]
        #
        #                 maybeMovedTo = self.army_moved_grid[y][x]
        #                 if maybeMovedTo:
        #                     # look for candidate tiles that army may have come from
        #                     bestCandTile = evaluateTileDiffsFog(curTile)
        #
        #                     if bestCandTile is not None:
        #                         byPlayer = curTile.player
        #                         if byPlayer == -1:
        #                             byPlayer = bestCandTile.player
        #                         self.set_tile_moved(curTile, bestCandTile, byPlayer=byPlayer)

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

                random.shuffle(tile.adjacents)
                random.shuffle(tile.movable)

        self.update_reachable()

    def update_reachable(self):
        pathableTiles = set()
        reachableTiles = set()

        queue = deque()

        for gen in self.generals:
            if gen is not None:
                queue.append(gen)
                self.players[gen.player].general = gen

        while len(queue) > 0:
            tile = queue.popleft()
            isNeutCity = tile.isCity and tile.isNeutral
            tileIsPathable = not tile.isNotPathable
            if tile not in pathableTiles and tileIsPathable and not isNeutCity:
                pathableTiles.add(tile)
                for movable in tile.movable:
                    queue.append(movable)
                    reachableTiles.add(movable)

        self.pathableTiles = pathableTiles
        self.reachableTiles = reachableTiles

    def clear_deltas_and_score_history(self):
        self.scoreHistory = [None for i in range(50)]
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
        self.pathableTiles.discard(tile)
        tile.tile = TILE_MOUNTAIN
        tile.isCity = False
        tile.army = 0
        tile.player = -1
        tile.isMountain = True
        tile.isGeneral = False

    def set_tile_probably_moved(self, toTile: Tile, fromTile: Tile, fullFromDiffCovered = True, fullToDiffCovered = True, byPlayer = -1):
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

        logging.info(f'MOVE {repr(fromTile)} -> {repr(toTile)} (fullFromDiffCovered {fullFromDiffCovered}, fullToDiffCovered {fullToDiffCovered})')
        self.army_moved_grid[fromTile.y][fromTile.x] = self.army_moved_grid[fromTile.y][fromTile.x] and not fullFromDiffCovered
        # if not self.USE_OLD_MOVEMENT_DETECTION:
        fromTile.delta.armyMovedHere = fromTile.delta.armyMovedHere and not fullFromDiffCovered

        expectedDelta = self._get_expected_delta_amount_toward(fromTile, toTile)
        # used to be if value greater than 75 or something
        if not fromTile.visible:
            fromDelta = expectedDelta
            # if fromTile.player != byPlayer:
            #     fromDelta = 0 - expectedDelta

            fromTile.army += fromDelta
            fromTile.delta.armyDelta = fromDelta
            if fromTile.player != byPlayer:
                fromTile.player = byPlayer
                if fromTile.army > 0 and fromTile.delta.oldOwner != self.player_index:
                    msg = f'fromTile was neutral/otherPlayer {fromTile.delta.oldOwner} with positive army {fromTile.army} in the fog. From->To: {repr(fromTile)} -> {repr(toTile)}'
                    if ENABLE_DEBUG_ASSERTS:
                        raise AssertionError(msg)
                    else:
                        logging.error(msg)
                        fromTile.army = 0 - fromTile.army
                if fromTile.isUndiscoveredObstacle:
                    fromTile.isCity = True
                    fromTile.army = 0

            self.set_fog_moved_from_army_incremented(fromTile, byPlayer, expectedDelta)

        # only say the army is completely covered if the confidence was high, otherwise we can have two armies move here from diff players
        self.army_moved_grid[toTile.y][toTile.x] = self.army_moved_grid[toTile.y][toTile.x] and not fullToDiffCovered
        # if not self.USE_OLD_MOVEMENT_DETECTION:
        toTile.delta.armyMovedHere = toTile.delta.armyMovedHere and not fullToDiffCovered

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
                # toTile.delta.unexplainedDelta = 0

        # prefer leaving enemy move froms, as they're harder for armytracker to track since it doesn't have the last move spelled out like it does for friendly moves.
        if toTile.delta.fromTile is None or toTile.delta.fromTile.delta.oldOwner != self.player_index:
            toTile.delta.fromTile = fromTile

        if fullFromDiffCovered:
            fromTile.delta.unexplainedDelta = 0
        if fullToDiffCovered:
            toTile.delta.unexplainedDelta = 0

        fromTile.delta.toTile = toTile
        logging.info(f'  done: {repr(fromTile)} -> {repr(toTile)}')

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

        self.set_tile_probably_moved(
            toTile,
            fromTile,
            fullFromDiffCovered,
            fullToDiffCovered,
            byPlayer=byPlayer,
        )

        if byPlayer >= 0:
            movingPlayer = self.players[byPlayer]

            if toTile.delta.oldOwner != toTile.player and toTile.player == byPlayer:
                movingPlayer.unexplainedTileDelta -= 1
                logging.info(f'   captured a tile, dropping the player tileDelta from unexplained for capturer p{movingPlayer.index} ({movingPlayer.unexplainedTileDelta + 1}->{movingPlayer.unexplainedTileDelta}).')
                if toTile.delta.oldOwner != -1:
                    attackedPlayer = self.players[toTile.delta.oldOwner]
                    attackedPlayer.unexplainedTileDelta += 1
                    logging.info(f'   captured a tile, dropping the player tileDelta from unexplained for capturee p{attackedPlayer.index} ({attackedPlayer.unexplainedTileDelta - 1}->{attackedPlayer.unexplainedTileDelta}).')

            movingPlayer.last_move = (fromTile, toTile)

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

    def _is_exact_army_movement_delta_match(self, source: Tile, dest: Tile):
        if source.delta.imperfectArmyDelta:
            return self._is_exact_lost_vision_movement_delta_match(source, dest)
        if dest.delta.imperfectArmyDelta:
            return False
        if self._move_would_violate_known_player_deltas(source, dest):
            return False

        deltaToDest = self._get_expected_delta_amount_toward(source, dest)
        if deltaToDest == dest.delta.unexplainedDelta:
            return True
        return False

    def _is_exact_lost_vision_movement_delta_match(self, source: Tile, dest: Tile):
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

    def _get_expected_delta_amount_toward(self, source: Tile, dest: Tile, moveHalf: bool = False) -> int:
        sourceDelta = source.delta.unexplainedDelta
        sameOwnerMove = source.delta.oldOwner == dest.delta.oldOwner and source.delta.oldOwner != -1
        teamMateMove = source.delta.oldOwner != dest.delta.oldOwner and self._teams[source.delta.oldOwner] == self._teams[dest.delta.oldOwner]
        if not source.visible:
            if not source.delta.lostSight:
                sourceDelta = dest.delta.unexplainedDelta

                # if not dest.visible:
                #     sourceDelta = source.delta.oldArmy - 1
                #     # OK so this ^ was wrong, all tests pass with it commented out, should have been:
                #     sourceDelta = 0 - (source.delta.oldArmy - 1)

            else:
                sourceDelta = 0 - (source.delta.oldArmy - 1)
                if moveHalf:
                    sourceDelta = 0 - source.delta.oldArmy // 2

            # TODO does this need to get fancier with potential movers vs the dest owner...?
            # TODO try commenting this out...?
            sameOwnerMove = (sameOwnerMove or (source.player == -1 and not source.delta.lostSight)) and dest.delta.oldOwner != -1
            # TODO should check move-half too probably
            # if source.player == -1:
            #     # then just assume same owner move...?
            #     sourceDelta = dest.delta.unexplainedDelta
        elif moveHalf:
            raise AssertionError(f'cannot provide moveHalf directive for visible tile {str(source)}, visible tiles exclusively use tile deltas.')
        if sameOwnerMove:
            return 0 - sourceDelta
        if teamMateMove:
            if not dest.isGeneral:
                return 2 * dest.delta.oldArmy + sourceDelta
            else:
                return 0 - sourceDelta
        return sourceDelta

    def _apply_last_player_move(self, last_player_index_submitted_move: typing.Tuple[Tile, Tile, bool]) -> typing.Tuple[Tile, Tile] | None:
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
        source.delta.armyMovedHere = False
        dest.delta.armyMovedHere = False

        logging.info(
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

        likelyDroppedMove = False
        if source.delta.unexplainedDelta == 0 and source.visible:
            likelyDroppedMove = True
            if dest.delta.unexplainedDelta == 0 and dest.visible:
                logging.error(
                    f'    map determined player DEFINITELY dropped move {str(last_player_index_submitted_move)}. Setting last move to none...')
                self.last_player_index_submitted_move = None
                return None
            else:
                logging.error(
                    f'    map determined player PROBABLY dropped move {str(last_player_index_submitted_move)}, but the dest DID have an army delta, double check on this... Continuing in case this is 2v2 BS or something.')

        # ok, then probably we didn't drop a move.

        actualSrcDelta = source.delta.unexplainedDelta
        if source.delta.lostSight:
            actualSrcDelta = -1 - source.delta.oldArmy

        actualDestDelta = dest.delta.unexplainedDelta

        srcUnexpectedDelta = actualSrcDelta - expectedSourceDelta
        sourceDeltaMismatch = srcUnexpectedDelta != 0

        destUnexpectedDelta = actualDestDelta - expectedDestDelta
        destDeltaMismatch = destUnexpectedDelta != 0

        weHadPriority = MapBase.player_had_priority_over_other(self.player_index, dest.delta.oldOwner, self.turn)

        sourceDefinitelyKilledWithPriority = not source.visible and not dest.visible and sourceWouldHaveCappedDest

        # check for mutual attack
        if (
            sourceDeltaMismatch
            and destUnexpectedDelta == srcUnexpectedDelta
            and dest.delta.oldOwner != self.player_index
            and dest.delta.oldOwner not in self.teammates
            and dest.delta.oldOwner != -1
        ):
            logging.info(f'MOVE {str(last_player_index_submitted_move)} was mutual attack?')
            self.set_tile_moved(toTile=source, fromTile=dest, fullFromDiffCovered=True, fullToDiffCovered=True, byPlayer=dest.delta.oldOwner)
            if actualDestDelta <= expectedSourceDelta:
                logging.info(f'   Mutual attack appears to have fully cancelled out our move, returning no move from us.')
                # source.delta.armyMovedHere = True
                self.last_player_index_submitted_move = None
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
                    and (tile.delta.unexplainedDelta != 0 or not tile.visible)
                    #and (tile.delta.oldOwner != self.player_index or tile.delta.newOwner != self.player_index)
            ):
                destHasEnDeltasNearby = True

        sourceWasCaptured = False
        sourceWasAttackedWithPriority = False
        # if sourceDeltaMismatch or source.player != self.player_index or (actualDestDelta == 0 and sourceHasEnPriorityDeltasNearby):
        if sourceDeltaMismatch or source.player != self.player_index or (destDeltaMismatch and sourceHasEnPriorityDeltasNearby) or sourceDefinitelyKilledWithPriority:
            if sourceHasEnPriorityDeltasNearby:
                sourceWasAttackedWithPriority = True
                if source.player != self.player_index or not source.visible:
                    sourceWasCaptured = True
                    logging.info(
                        f'MOVE {str(last_player_index_submitted_move)} seems to have been captured with priority. Nuking our last move.')
                    if destDeltaMismatch:
                        logging.error(
                            f'  ^ {str(last_player_index_submitted_move)} IS QUESTIONABLE THOUGH BECAUSE DEST DID HAVE AN UNEXPLAINED DIFF. NUKING ANYWAY.')
                    # self.unaccounted_tile_diffs[source] = srcUnexpectedDelta  # negative number
                    # source.delta.destUnexpectedDelta = srcUnexpectedDelta
                    source.delta.armyMovedHere = True
                    self.last_player_index_submitted_move = None
                    return None
                else:
                    if actualDestDelta == 0:
                        logging.info(
                            f'MOVE {str(last_player_index_submitted_move)} seems to have been attacked with priority down to where we dont capture anything. Nuking our last move.')
                        # self.unaccounted_tile_diffs[source] = srcUnexpectedDelta  # negative number
                        # source.delta.destUnexpectedDelta = srcUnexpectedDelta
                        source.delta.armyMovedHere = True
                        self.last_player_index_submitted_move = None
                        return None
                    # source.delta.destUnexpectedDelta -= actualDestDelta
                    # source.delta.armyMovedHere = True
                    # # source.delta.imperfectArmyDelta = destHasEnDeltasNearby
                    # # return source, dest
            elif source.player != self.player_index:
                logging.info(
                    f'MOVE {str(last_player_index_submitted_move)} was capped WITHOUT priority..? Adding unexplained diff {srcUnexpectedDelta} based on actualSrcDelta {actualSrcDelta} - expectedSourceDelta {expectedSourceDelta}. Continuing with dest diff calc')
                # self.unaccounted_tile_diffs[source] = srcUnexpectedDelta  # negative number

                source.delta.unexplainedDelta = srcUnexpectedDelta - actualDestDelta + expectedDestDelta
                source.delta.armyMovedHere = True
                # TODO this is wrong...? Need to account for the amount of dest delta we think made it...?
                # dest.delta.destUnexpectedDelta = 0
            else:
                # we can get here if the source tile was attacked with priority but not for full damage, OR if it was attacked without priority for non full damage...
                destArmyInterferedToo = False
                if not destDeltaMismatch:
                    # then we almost certainly didn't have source attacked with priority.
                    logging.warning(
                        f'MOVE {str(last_player_index_submitted_move)} ? src attacked for srcUnexpectedDelta {srcUnexpectedDelta} WITHOUT priority based on actualSrcDelta {actualSrcDelta} vs expectedSourceDelta {expectedSourceDelta}')
                elif destHasEnDeltasNearby:
                    armyMadeItToDest = dest.delta.unexplainedDelta
                    srcUnexpectedDelta = expectedDestDelta - armyMadeItToDest
                    if source.army == 0:
                        srcUnexpectedDelta -= 1  # enemy can attack us down to 0 without flipping the tile, special case this

                    logging.warning(
                        f'MOVE {str(last_player_index_submitted_move)} ? src attacked for srcUnexpectedDelta {srcUnexpectedDelta} based on destDelta {dest.delta.unexplainedDelta} vs expectedDestDelta {expectedDestDelta}')
                else:
                    destArmyInterferedToo = True
                    # TODO what to do here?
                    logging.warning(
                        f'???MOVE {str(last_player_index_submitted_move)} ? player had priority but we still had a dest delta as well as source delta...?')
                    dest.delta.armyMovedHere = True

                source.delta.unexplainedDelta = srcUnexpectedDelta  # negative number
                source.delta.armyMovedHere = True
                if not destArmyInterferedToo:
                    # intentionally do nothing about the dest tile diff if we found a source tile diff, as it is really unlikely that both source and dest get interfered with on same turn.
                    # self.army_moved(army, dest, trackingArmies)
                    # TODO could be wrong
                    dest.delta.unexplainedDelta = 0
                    self.last_player_index_submitted_move = last_player_index_submitted_move
                    return source, dest
        else:
            # nothing happened, we moved the expected army off of source. Not unexplained.
            # self.unaccounted_tile_diffs.pop(source, 0)
            source.delta.unexplainedDelta = 0

        if destDeltaMismatch:
            if dest.delta.lostSight:
                # then we got attacked, possibly BY the dest tile.
                if dest.delta.oldArmy > source.delta.oldArmy - 1 and dest.delta.oldOwner != self.player_index:
                    # then dest could have attacked us.
                    dest.delta.armyMovedHere = True
                    dest.delta.imperfectArmyDelta = True
            else:
                # dest.delta.destUnexpectedDelta = destUnexpectedDelta
                # dest.delta.armyMovedHere = True
                if destHasEnDeltasNearby:
                    dest.delta.unexplainedDelta = destUnexpectedDelta
                    dest.delta.armyMovedHere = True
                    # dest.delta.imperfectArmyDelta = sourceHasEnPriorityDeltasNearby

                if sourceHasEnPriorityDeltasNearby:
                    logging.info(
                        f'MOVE {str(last_player_index_submitted_move)} with expectedDestDelta {expectedDestDelta} likely collided with destUnexpectedDelta {destUnexpectedDelta} at dest OR SOURCE based on actualDestDelta {actualDestDelta}.')
                else:
                    logging.info(
                        f'MOVE {str(last_player_index_submitted_move)} with expectedDestDelta {expectedDestDelta} likely collided with destUnexpectedDelta {destUnexpectedDelta} at DEST based on actualDestDelta {actualDestDelta}.')

                # TODO this might need to also happen when lost sight, but idk how to get the right delta...? Repro...?
                if sourceHasEnPriorityDeltasNearby:
                    # the source tile could have been attacked for non-lethal damage BEFORE the move was made to target.
                    source.delta.unexplainedDelta = destUnexpectedDelta
                    if dest.delta.oldOwner != self.player_index:
                        source.delta.unexplainedDelta = 0 - destUnexpectedDelta
                    # source.delta.unexplainedDelta = srcUnexpectedDelta
                    # if dest.delta.oldOwner != self.player_index:
                    #     source.delta.unexplainedDelta = 0 - destUnexpectedDelta
                    source.delta.imperfectArmyDelta = destHasEnDeltasNearby
                    source.delta.armyMovedHere = True
        else:
            logging.info(
                f'!MOVE {str(last_player_index_submitted_move)} made it to dest with no issues, moving army.\r\n    expectedDestDelta {expectedDestDelta}, actualDestDelta {actualDestDelta}, expectedSourceDelta {expectedSourceDelta}, actualSrcDelta {actualSrcDelta}, sourceWasAttackedWithPriority {sourceWasAttackedWithPriority}, sourceWasCaptured {sourceWasCaptured}')
            # self.unaccounted_tile_diffs.pop(dest, 0)
            dest.delta.unexplainedDelta = 0
            # dest.delta.armyMovedHere = False
            # if dest.player != self.map.player_index:
            # skip.add(dest)  # might not need this at alll.....? TODO ??

        if actualDestDelta == 0 and dest.delta.unexplainedDelta == 0:
            # then the move DEFINITELY didn't happen / was captured
            self.last_player_index_submitted_move = None
            return None
        
        self.last_player_index_submitted_move = last_player_index_submitted_move
        return source, dest

    # def is_exact_fog_move(self, tile: Tile, candidateTile: Tile) -> bool:
    #     # print(str(tile.army) + " : " + str(candidateTile.army))
    #     if candidateTile.visible:
    #         if tile.army + candidateTile.delta.armyDelta < -1 and candidateTile.player != -1:
    #             tile.player = candidateTile.player
    #             tile.delta.newOwner = candidateTile.player
    #             oldArmy = tile.army
    #             tile.army = 0 - candidateTile.delta.armyDelta - tile.army
    #             # THIS HANDLED EXTERNAL IN THE UPDATE LOOP, AFTER THIS LOGIC HAPPENS
    #             # if tile.isCity and isCityBonusTurn:
    #             #     tile.army += 1
    #             # if isArmyBonusTurn:
    #             #     tile.army += 1
    #             logging.info(f" (islandFog 1) tile {str(tile)} army from {oldArmy} to {tile.army}")
    #             return 100
    #     elif tile.army - candidateTile.army < -1 and candidateTile.player != -1:
    #         tile.player = candidateTile.player
    #         tile.delta.newOwner = candidateTile.player
    #         oldArmy = tile.army
    #         tile.army = candidateTile.army - tile.army - 1
    #         oldCandArmy = candidateTile.army
    #         candidateTile.army = 1
    #         # THIS HANDLED EXTERNAL IN THE UPDATE LOOP, AFTER THIS LOGIC HAPPENS
    #         # if candidateTile.isCity and isCityBonusTurn:
    #         #     candidateTile.army += 1
    #         # if isArmyBonusTurn:
    #         #     candidateTile.army += 1
    #         logging.info(f" (islandFog 2) tile {str(tile)} army from {oldArmy} to {tile.army}")
    #         logging.info(
    #             f" (islandFog 2) candTile {candidateTile.toString()} army from {oldCandArmy} to {candidateTile.army}")
    #         return 100
    #     return -100

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
                logging.info(f" (islandFog 1) tile {str(tileLost)} army from {oldArmy} to {tileLost.army}")
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
            logging.info(f" (islandFog 2) tile {str(tileLost)} army from {oldArmy} to {tileLost.army}")
            logging.info(
                f" (islandFog 2) candTile {killedByTile.toString()} army from {oldCandArmy} to {killedByTile.army}")
            return 100
        return -100

    def detect_movement_and_populate_unexplained_diffs(self):
        possibleMovesDict: typing.Dict[Tile, typing.List[Tile]] = {}

        for player in self.players:
            player.last_move = None

        if self.generals[self.player_index] is None or self.generals[self.player_index].player != self.player_index:
            # we are dead
            return

        # TODO for debugging only
        tilesWithDiffsPreOwn = [t for t in self.get_all_tiles() if t.delta.unexplainedDelta != 0]
        tilesWithMovedHerePreOwn = [t for t in self.get_all_tiles() if t.delta.armyMovedHere]

        logging.info(f'Tiles with diffs pre-own: {str([str(t) for t in tilesWithDiffsPreOwn])}')
        logging.info(f'Tiles with MovedHere pre-own: {str([str(t) for t in tilesWithMovedHerePreOwn])}')

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

        skipPlayers: typing.Set[int] = set()
        for p in self.players:
            if p.dead and p.capturedBy is not None:
                skipPlayers.add(p.index)

        self.run_positive_delta_movement_scan(skipPlayers, possibleMovesDict, allowFogSource=False)

        self.run_attacked_tile_movement_scan(skipPlayers, possibleMovesDict, allowFogSource=False)

        self.run_positive_delta_movement_scan(skipPlayers, possibleMovesDict, allowFogSource=True)

        # TODO for debugging only
        tilesWithDiffsPreFog = [t for t in self.get_all_tiles() if t.delta.unexplainedDelta != 0]
        tilesWithMovedHerePreFog = [t for t in self.get_all_tiles() if t.delta.armyMovedHere]

        logging.info(f'Tiles with diffs at pre-FOG: {str([str(t) for t in tilesWithDiffsPreFog])}')
        logging.info(f'Tiles with MovedHere at pre-FOG: {str([str(t) for t in tilesWithMovedHerePreFog])}')

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
                if sourceTile.delta.oldOwner == -1 or sourceTile.delta.oldOwner in skipPlayers:
                    continue

                potentialDests = []
                sourceWasAttackedNonLethalOrVacated = sourceTile.delta.armyDelta < 0 and sourceTile.delta.oldOwner == sourceTile.delta.newOwner
                # sourceWasAttackedNonLethalOrVacated = sourceTile.delta.oldArmy + sourceTile.delta.armyDelta < sourceTile.delta.oldArmy
                for potentialDest in sourceTile.movable:
                    if potentialDest.visible and not potentialDest.delta.gainedSight:
                        continue
                    if sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_match(sourceTile, potentialDest):
                        logging.info(
                            f'FOG SOURCE SCAN DEST {repr(potentialDest)} SRC {repr(sourceTile)} WAS sourceWasAttackedNonLethalOrVacated {sourceWasAttackedNonLethalOrVacated} FORCE-SELECTED DUE TO EXACT MATCH, BREAKING EARLY')
                        potentialDests = [potentialDest]
                        break
                    if potentialDest.delta.oldOwner in skipPlayers:
                        continue

                    if potentialDest.delta.imperfectArmyDelta and sourceWasAttackedNonLethalOrVacated:
                        logging.info(
                            f'FOG SOURCE SCAN DEST {repr(potentialDest)} SRC {repr(sourceTile)} WAS potentialDest.delta.imperfectArmyDelta and sourceWasAttackedNonLethalOrVacated, INCLUDING IT AS POTENTIAL DEST')
                        potentialDests.append(potentialDest)
                    elif self._is_partial_army_movement_delta_match(source=sourceTile, dest=potentialDest):
                        logging.info(
                            f'FOG SOURCE SCAN DEST {repr(potentialDest)} SRC {repr(sourceTile)} WAS self._is_partial_army_movement_delta_match(source=sourceTile, dest=potentialDest), INCLUDING IT AS POTENTIAL DEST')
                        potentialDests.append(potentialDest)

                if len(potentialDests) == 1:
                    exclusiveDest = potentialDests[0]
                    # we have our dest...?
                    exactMatch = (
                            not sourceTile.delta.imperfectArmyDelta
                            and not exclusiveDest.delta.imperfectArmyDelta
                            and self._is_exact_army_movement_delta_match(exclusiveDest, sourceTile)
                    )

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

                    logging.info(
                        f'FOG SOURCE SCAN DEST {repr(exclusiveDest)} SRC {repr(sourceTile)} WAS EXCLUSIVE DEST, EXACT MATCH {exactMatch} INCLUDING IN MOVES, CALCED PLAYER {byPlayer}')

                    self.set_tile_moved(
                        exclusiveDest,
                        sourceTile,
                        fullFromDiffCovered=exactMatch,
                        fullToDiffCovered=exactMatch,
                        byPlayer=byPlayer)
                else:
                    if len(potentialDests) > 0:
                        logging.info(f'FOG SOURCE SCAN SRC {repr(sourceTile)} RESULTED IN MULTIPLE DESTS {repr([repr(s) for s in potentialDests])}, UNHANDLED FOR NOW')
                    possibleMovesDict[sourceTile] = potentialDests

        self.run_attacked_tile_movement_scan(skipPlayers, possibleMovesDict, allowFogSource=True)

        # TODO for debugging only
        tilesWithDiffsPreIsland = [t for t in self.get_all_tiles() if t.delta.unexplainedDelta != 0]
        tilesWithMovedHerePreIsland = [t for t in self.get_all_tiles() if t.delta.armyMovedHere]

        logging.info(f'Tiles with diffs at pre-ISLAND-VISION-LOSS: {str([str(t) for t in tilesWithDiffsPreIsland])}')
        logging.info(f'Tiles with MovedHere at pre-ISLAND-VISION-LOSS: {str([str(t) for t in tilesWithMovedHerePreIsland])}')

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
                        logging.info(f'ISLAND FOG DEST {repr(destTile)}: SRC {repr(potentialSource)} SKIPPED BECAUSE DIDNT LOSE VISION OF SOURCE, WHICH MEANS IT SHOULD HAVE BEEN CAUGHT BY ANOTHER HANDLER ALREADY (?)')
                        continue
                    if evaluate_island_fog_move(destTile, potentialSource):
                        byPlayer = potentialSource.delta.oldOwner

                        logging.info(
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
                        logging.info(f'ISLAND FOG DEST {repr(destTile)} RESULTED IN MULTIPLE SOURCES {repr([repr(s) for s in potentialSources])}, UNHANDLED FOR NOW')
                    possibleMovesDict[destTile] = potentialSources
        # TODO compare potential sources limited to one per player.

        # TODO for debugging only
        tilesWithDiffsEnd = [t for t in self.get_all_tiles() if t.delta.unexplainedDelta != 0]
        tilesWithMovedHereEnd = [t for t in self.get_all_tiles() if t.delta.armyMovedHere]

        logging.info(f'Tiles with diffs at end: {str([str(t) for t in tilesWithDiffsEnd])}')
        logging.info(f'Tiles with MovedHere at end: {str([str(t) for t in tilesWithMovedHereEnd])}')

        for t in self.get_all_tiles():
            if t.delta.unexplainedDelta == 0:
                continue
            if not t.visible:
                continue
            if t.player == -1:
                continue
            if t in self.army_emergences:
                continue

            self.army_emergences[t] = (t.delta.unexplainedDelta, t.player)

        return

    def calculate_player_deltas(self):
        myPlayer = self.players[self.player_index]

        lastScores = self.scoreHistory[1]
        if lastScores is None:
            logging.info("no last scores?????")
            return

        expectedFriendlyDelta = 0

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

                if self.is_army_bonus_turn:
                    expectedFriendlyDelta += teammatePlayer.tileCount
                if self.is_city_bonus_turn:
                    expectedFriendlyDelta += teammatePlayer.cityCount

                actualFriendlyDelta += teammatePlayer.score - lastScores[teammatePlayer.index].total

        friendlyFightDelta = expectedFriendlyDelta - actualFriendlyDelta

        logging.info(f"myPlayer score {myPlayer.score}, lastScores myPlayer total {lastScores[myPlayer.index].total}, friendlyFightDelta {friendlyFightDelta}")

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

        teamCurrentCities = 0
        for teamIndex, teamList in teamDict.items():
            actualEnemyTeamDelta = 0
            expectedEnemyTeamDelta = 0
            teamCityCount = 0
            for playerIndex in teamList:
                teamPlayer = self.players[playerIndex]

                if teamPlayer.dead:
                    teamPlayer.expectedScoreDelta = 0
                    teamPlayer.actualScoreDelta = 0
                    teamPlayer.cityCount = 0
                    continue

                expectedEnemyDelta = 0
                if self.is_army_bonus_turn:
                    expectedEnemyDelta += teamPlayer.tileCount
                if self.is_city_bonus_turn:
                    expectedEnemyDelta += teamPlayer.cityCount

                logging.info(
                    f'teamPlayer score {teamPlayer.score}, lastScores teamPlayer total {lastScores[teamPlayer.index].total}')

                teamPlayer.actualScoreDelta = teamPlayer.score - lastScores[teamPlayer.index].total
                teamPlayer.expectedScoreDelta = expectedEnemyDelta
                expectedEnemyTeamDelta += expectedEnemyDelta

                # potentialEnemyCities = teamPlayer.actualScoreDelta - teamPlayer.

                actualEnemyTeamDelta += teamPlayer.actualScoreDelta

                teamCurrentCities += teamPlayer.cityCount
                teamCityCount += teamPlayer.cityCount

                # nothing past here runs for us
                if self.player_index in teamList:
                    teamPlayer.cityCount = len(teamPlayer.cities) + 1
                    continue

            newCityCount = teamCityCount
            if self.is_city_bonus_turn:
                if self.remainingPlayers == 2 or self.is_2v2:
                    # if NOT 1v1 we use the outer, dumber city count calculation that works reliably for FFA.
                    # in a 1v1, if we lost army, then opponent also lost equal army (unless we just took a neutral tile)
                    # this means we can still calculate city counts, even when fights are ongoing and both players are losing army
                    # so we get the amount of unexpected delta on our player, and add that to actual opponent delta, and get the opponents city count

                    realEnemyCities = teamCityCount + actualEnemyTeamDelta + friendlyFightDelta - expectedEnemyTeamDelta

                    # if teamPlayer.

                    if realEnemyCities <= -30:
                        # then opp just took a neutral city
                        newCityCount += 1
                        logging.info(f"set team {teamIndex} cityCount += 1 to {newCityCount} because it appears they just took a city based on realEnemyCities {realEnemyCities}.")
                    elif realEnemyCities >= 30:
                        # then our player just took a neutral city, noop
                        logging.info(
                            "myPlayer just took a city? (or fighting in ffa) ignoring realEnemyCities this turn, realEnemyCities >= 38 and actualMeDelta < -30")
                    else:
                        newCityCount = realEnemyCities
                        logging.info(
                            f"want to set team {teamIndex} cityCount to {newCityCount}. "
                            f"\nexpectedFriendlyDelta {expectedFriendlyDelta}, actualFriendlyDelta {actualFriendlyDelta},"
                            f"\nexpectedEnemyTeamDelta {expectedEnemyTeamDelta}, actualEnemyTeamDelta {actualEnemyTeamDelta},"
                            f"\nfrFightDelta {friendlyFightDelta} results in realEnemyCities {realEnemyCities} vs teamCurrentCities {teamCurrentCities}")

                logging.info(f'cities for team {teamIndex}, as {newCityCount} vs current {teamCurrentCities}?')

                if self.player_index in teamList:
                    # we have perfect info of our own cities
                    continue

                if self.remainingPlayers > 2 and self.is_2v2 and newCityCount - teamCurrentCities > 5 and teamCurrentCities > 1:
                    logging.info(f'miscounting cities for team {teamIndex}, as {newCityCount} vs current {teamCurrentCities}? ignoring')
                    continue
                if friendlyFightDelta == 0:
                    logging.info(f'Trying to make cities for team {teamIndex} match {newCityCount} vs current {teamCurrentCities}?')
                    sum = 0
                    for playerIndex in teamList:
                        teamPlayer = self.players[playerIndex]
                        if teamPlayer.dead:
                            continue
                        sum += teamPlayer.cityCount

                    while sum < newCityCount:
                        for playerIndex in teamList:
                            teamPlayer = self.players[playerIndex]
                            if teamPlayer.dead:
                                continue
                            teamPlayer.cityCount += 1
                            logging.info(f'Incrementing p{playerIndex} cities by 1 from {teamPlayer.cityCount - 1} to {teamPlayer.cityCount}')
                            sum += 1
                            if sum >= newCityCount:
                                break

                    while sum > newCityCount:
                        for playerIndex in teamList:
                            teamPlayer = self.players[playerIndex]
                            if teamPlayer.dead:
                                continue
                            teamPlayer.cityCount -= 1
                            logging.info(f'Decrementing p{playerIndex} cities by 1 from {teamPlayer.cityCount + 1} to {teamPlayer.cityCount}')
                            sum -= 1
                            if sum <= newCityCount:
                                break

        for player in self.players:
            playerDeltaDiff = player.actualScoreDelta - player.expectedScoreDelta
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
            else:
                player.fighting_with_player = -1

    def _move_would_violate_known_player_deltas(self, source: Tile, dest: Tile):
        knowSourceOwner = source.was_visible_last_turn() or (self.remainingPlayers == 2 and source.discovered and source.player >= 0)
        if knowSourceOwner:
            sourceOwner = self.players[source.delta.oldOwner]
            knowDestOwner = dest.was_visible_last_turn() or (self.remainingPlayers == 2 and dest.discovered and dest.delta.oldOwner >= 0)
            if knowDestOwner:
                destOwner = None

                if dest.delta.oldOwner >= 0:
                    destOwner = self.players[dest.delta.oldOwner]
                if sourceOwner == destOwner:
                    # ok we know the players are fighting with each other, we know one move attacked the source tile
                    if sourceOwner.unexplainedTileDelta == 1:
                        logging.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} can be discarded '
                                     f'outright, as it would not have captured a tile and the player '
                                     f'DID capture a tile.')

                        return True

                elif self.remainingPlayers == 2 and destOwner is not None and destOwner.unexplainedTileDelta == 1:
                    logging.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} can be discarded '
                                 f'outright, as it would have captured a tile and instead dest player'
                                 f' p{destOwner.index} gained tiles.')
                    return True

                elif self.remainingPlayers == 2 and sourceOwner.unexplainedTileDelta < 0:
                    logging.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} can be discarded '
                                 f'outright, as it would have captured a tile and instead they lost at '
                                 f'least one net tile. This should be accurate unless the player is being '
                                 f'attacked by more than two players at once.')
                    return True

                elif self.remainingPlayers == 2 and sourceOwner.unexplainedTileDelta == 0:
                    logging.info(f'move {str(source)}->{str(dest)} by p{sourceOwner.index} is sketchy but allowed, '
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

        if self.is_army_bonus_turn:
            army += 1
        if (tile.isCity or tile.isGeneral) and self.is_city_bonus_turn:
            army += 1

        tile.army = army
        tile.delta.oldOwner = byPlayer
        tile.delta.newOwner = byPlayer

    def set_fog_emergence(self, fromTile: Tile, armyEmerged: int, byPlayer: int):
        logging.info(f'+++EMERGENCE {repr(fromTile)} = {armyEmerged}')
        self.army_emergences[fromTile] = (armyEmerged, byPlayer)

    def run_positive_delta_movement_scan(self, skipPlayers: typing.Set[int], possibleMovesDict: typing.Dict[Tile, typing.List[Tile]], allowFogSource: bool):
        fogFlag = ""
        if allowFogSource:
            fogFlag = " (FOG)"

        # TODO for debugging only
        tilesWithDiffsPrePos = [t for t in self.get_all_tiles() if t.delta.unexplainedDelta != 0]
        tilesWithMovedHerePrePos = [t for t in self.get_all_tiles() if t.delta.armyMovedHere]

        logging.info(f'Tiles with diffs pre-POS{fogFlag}: {str([str(t) for t in tilesWithDiffsPrePos])}')
        logging.info(f'Tiles with MovedHere pre-POS{fogFlag}: {str([str(t) for t in tilesWithMovedHerePrePos])}')

        # scan for tiles with positive deltas first, those tiles MUST have been gathered to from a friendly tile by the player they are on, letting us eliminate tons of options outright.
        for x in range(self.cols):
            for y in range(self.rows):
                destTile = self.grid[y][x]
                if not destTile.delta.armyMovedHere or destTile.delta.imperfectArmyDelta:
                    continue
                if destTile.delta.oldOwner in skipPlayers:
                    continue

                potentialSources = []
                # destWasAttackedNonLethalOrVacatedOrUnmoved = destTile.delta.unexplainedDelta <= 0 and self._teams[destTile.delta.oldOwner] != self._teams[destTile.delta.newOwner]
                wasFriendlyMove = self._teams[destTile.delta.oldOwner] == self._teams[destTile.delta.newOwner] and destTile.delta.oldOwner != destTile.delta.newOwner
                destWasAttackedNonLethalOrVacatedOrUnmoved = destTile.delta.unexplainedDelta <= 0 and not wasFriendlyMove
                if destWasAttackedNonLethalOrVacatedOrUnmoved:
                    logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} SKIPPED BECAUSE destWasAttackedNonLethalOrVacatedOrUnmoved {destWasAttackedNonLethalOrVacatedOrUnmoved}')
                    continue

                for potentialSource in destTile.movable:
                    if potentialSource.delta.oldOwner == self.player_index:
                        # we already track our own moves successfully prior to this.
                        continue
                    if not allowFogSource and not potentialSource.visible and not potentialSource.delta.lostSight:
                        continue
                    if potentialSource.delta.oldOwner in skipPlayers:
                        continue
                    if potentialSource.was_visible_last_turn() and self._teams[potentialSource.delta.oldOwner] != self._teams[destTile.delta.oldOwner]:
                        # only the player who owns the resulting tile can move one of their own tiles into it. TODO 2v2...?
                        logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)}: SRC {repr(potentialSource)} SKIPPED BECAUSE potentialSource.was_visible_last_turn() and potentialSource.delta.oldOwner != destTile.player')
                        continue
                    if destTile.delta.armyDelta > 0 and destTile.was_visible_last_turn() and potentialSource.was_visible_last_turn() and potentialSource.delta.armyDelta > 0:
                        msg = f'This shouldnt be possible, two of the same players tiles increasing on the same turn...? {repr(potentialSource)} - {repr(destTile)}'
                        if ENABLE_DEBUG_ASSERTS:
                            raise AssertionError(msg)
                        else:
                            logging.error(msg)
                        # continue

                    sourceWasAttackedNonLethalOrVacated = potentialSource.delta.armyDelta < 0
                    # if  sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_match(potentialSource, destTile):
                    if sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_match(potentialSource, destTile):
                        potentialSources = [potentialSource]
                        logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} FORCE-SELECTED DUE TO EXACT MATCH, BREAKING EARLY')
                        break

                    # no effect on diagonal
                    # if potentialSource.delta.imperfectArmyDelta and (not sourceWasAttackedNonLethalOrVacated or (potentialSource.player >= 0 and potentialSource.player != destTile.delta.oldOwner)):
                    if potentialSource.delta.imperfectArmyDelta and not self._move_would_violate_known_player_deltas(potentialSource, destTile):
                        logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} INCLUDED AS POTENTIAL SOURCE BUT CONTINUING TO LOOK FOR MORE')
                        potentialSources.append(potentialSource)
                    elif self.remainingPlayers > 2 and self._is_partial_army_movement_delta_match(source=potentialSource, dest=destTile):
                        if destTile.army < 3:
                            logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} refusing to include potential FFA third party attack because tile appears to have been moved, something seems messed up...')
                        else:
                            logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} including potential FFA third party attack from fog as tile damager.')
                            potentialSources.append(potentialSource)

                if len(potentialSources) == 1:
                    exclusiveSrc = potentialSources[0]
                    # we have our source...?
                    exactMatch = (
                            not destTile.delta.imperfectArmyDelta
                            and not exclusiveSrc.delta.imperfectArmyDelta
                            and self._is_exact_army_movement_delta_match(exclusiveSrc, destTile)
                    )

                    logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(exclusiveSrc)} WAS EXCLUSIVE SOURCE, EXACT MATCH {exactMatch} INCLUDING IN MOVES')

                    byPlayer = destTile.delta.oldOwner
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
                        logging.info(f'POS DELTA SCAN{fogFlag} DEST {repr(destTile)} RESULTED IN MULTIPLE SOURCES {repr([repr(s) for s in potentialSources])}, UNHANDLED FOR NOW')
                    possibleMovesDict[destTile] = potentialSources

    def run_attacked_tile_movement_scan(self, skipPlayers: typing.Set[int], possibleMovesDict: typing.Dict[Tile, typing.List[Tile]], allowFogSource: bool):
        fogFlag = ""
        if allowFogSource:
            fogFlag = "(FOG) "

        # TODO for debugging only
        tilesWithDiffsPreSource = [t for t in self.get_all_tiles() if t.delta.unexplainedDelta != 0]
        tilesWithMovedHerePreSource = [t for t in self.get_all_tiles() if t.delta.armyMovedHere]

        logging.info(f'Tiles with diffs pre-ATTK{fogFlag}: {str([str(t) for t in tilesWithDiffsPreSource])}')
        logging.info(f'Tiles with MovedHere pre-ATTK{fogFlag}: {str([str(t) for t in tilesWithMovedHerePreSource])}')

        # Then attacked dest tiles. This should catch obvious moves from fog as well as all moves between visible tiles.
        # currently also catches moves into fog, which it shouldnt...?
        for x in range(self.cols):
            for y in range(self.rows):
                destTile = self.grid[y][x]
                # if not destTile.delta.armyMovedHere:
                if not destTile.delta.armyMovedHere or destTile.delta.imperfectArmyDelta:
                    continue
                if not allowFogSource and not destTile.visible and not destTile.delta.lostSight:
                    continue
                if destTile.delta.oldOwner in skipPlayers:
                    continue

                potentialSources = []
                wasFriendlyMove = self._teams[destTile.delta.oldOwner] == self._teams[destTile.delta.newOwner] # and destTile.delta.oldOwner != destTile.delta.newOwner
                destWasAttackedNonLethalOrVacated = destTile.delta.armyDelta < 0 and wasFriendlyMove
                # destWasAttackedNonLethalOrVacated = True
                # destWasAttackedNonLethalOrVacated = destTile.delta.oldArmy + destTile.delta.armyDelta < destTile.delta.oldArmy
                for potentialSource in destTile.movable:
                    # we already track our own moves successfully prior to this.
                    if potentialSource.delta.oldOwner == self.player_index:
                        continue
                    if not allowFogSource and not potentialSource.visible and not potentialSource.delta.lostSight:
                        continue
                    if potentialSource.delta.oldOwner in skipPlayers:
                        continue
                    if potentialSource.delta.armyDelta > 0 and not potentialSource.delta.gainedSight:
                        logging.info(
                            f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)}: SRC {repr(potentialSource)} SKIPPED BECAUSE GATHERED TO, NOT ATTACKED. potentialSource.delta.armyDelta > 0')
                        # then this was DEFINITELY gathered to, which would make this not a potential source. 2v2 violates this
                        continue
                    wasFriendlyMove = self._teams[potentialSource.delta.oldOwner] == self._teams[potentialSource.delta.newOwner] and potentialSource.delta.oldOwner != potentialSource.delta.newOwner
                    sourceWasAttackedNonLethalOrVacated = (potentialSource.delta.unexplainedDelta <= 0 and not wasFriendlyMove) or potentialSource.delta.lostSight or (not potentialSource.visible and allowFogSource)
                    # sourceWasAttackedNonLethalOrVacated = potentialSource.delta.armyDelta < 0 or potentialSource.delta.lostSight or (not potentialSource.visible and allowFogSource)
                    # if  sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_match(potentialSource, destTile):
                    if sourceWasAttackedNonLethalOrVacated and self._is_exact_army_movement_delta_match(potentialSource, destTile):
                        potentialSources = [potentialSource]
                        logging.info(
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
                            logging.info(
                                f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} refusing to include potential FFA third party attack because tile appears to have been moved, something seems messed up...')
                        else:
                            logging.info(
                                f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(potentialSource)} including potential FFA third party attack from fog as tile damager.')
                            potentialSources.append(potentialSource)

                if len(potentialSources) == 1:
                    exclusiveSrc = potentialSources[0]
                    # we have our source...?
                    exactMatch = (
                            not destTile.delta.imperfectArmyDelta
                            and not exclusiveSrc.delta.imperfectArmyDelta
                            and self._is_exact_army_movement_delta_match(exclusiveSrc, destTile)
                    )

                    # if False and not exclusiveSrc.visible and destTile.delta.unexplainedDelta < 0 and not destTile.delta.gainedSight:
                    #     # then they moved into fog idiot, way more likely than being attacked on the edge of your vision by a player that isn't you...
                    #     self.set_tile_moved(
                    #         toTile=exclusiveSrc,
                    #         fromTile=destTile,
                    #         fullFromDiffCovered=exactMatch,
                    #         fullToDiffCovered=exactMatch,
                    #         byPlayer=destTile.delta.oldOwner)
                    # else:
                    byPlayer = exclusiveSrc.delta.oldOwner
                    if self.was_captured_this_turn(destTile):
                        byPlayer = destTile.player
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

                    logging.info(
                        f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(exclusiveSrc)} WAS EXCLUSIVE SOURCE, EXACT MATCH {exactMatch} INCLUDING IN MOVES, CALCED PLAYER {byPlayer}')

                    if byPlayer != -1:
                        self.set_tile_moved(
                            destTile,
                            exclusiveSrc,
                            fullFromDiffCovered=exactMatch,
                            fullToDiffCovered=exactMatch,
                            byPlayer=byPlayer)
                    else:
                        logging.error(
                            f'ATTK DELTA SCAN{fogFlag} DEST {repr(destTile)} SRC {repr(exclusiveSrc)} UNABLE TO EXECUTE DUE TO UNABLE TO FIND byPlayer THAT ISNT NEUTRAL')
                else:
                    if len(potentialSources) > 0:
                        logging.info(
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

    @staticmethod
    def get_teams_array(map: MapBase) -> typing.List[int]:
        teams = map.teams
        if teams is None:
            teams = [i for i in range(len(map.players))]

        teams.append(-1)  # put -1 at the end so that if -1 gets passed as the array index, the team is -1 for -1.

        return teams


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

    def convert_tile_server_index_to_x_y(self, tileIndex: int) -> typing.Tuple[int, int]:
        y = tileIndex // self.cols
        x = tileIndex % self.cols
        return x, y


def new_map_grid(map, initialValueXYFunc):
    return [[initialValueXYFunc(x, y) for y in range(map.rows)] for x in range(map.cols)]


def new_tile_grid(map, initialValueTileFunc):
    return [[initialValueTileFunc(map.grid[y][x]) for y in range(map.rows)] for x in range(map.cols)]


def new_value_grid(map, initValue) -> typing.List[typing.List[int]]:
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
