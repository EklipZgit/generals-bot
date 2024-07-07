from __future__ import annotations

import typing

import logbook

TILE_EMPTY = -1
TILE_MOUNTAIN = -2
TILE_FOG = -3
TILE_OBSTACLE = -4
TILE_LOOKOUT = -5
TILE_TELESCOPE = -6
MOUNTAIN_TILES = [TILE_LOOKOUT, TILE_MOUNTAIN, TILE_TELESCOPE]

PLAYER_CHAR_INDEX_PAIRS: typing.List[typing.Tuple[str, int]] = [
    ('a', 0),
    ('b', 1),
    ('c', 2),
    ('d', 3),
    ('e', 4),
    ('f', 5),
    ('g', 6),
    ('h', 7),
    ('i', 8),
    ('j', 9),
    ('k', 10),
    ('l', 11),
    ('m', 12),
    ('n', 13),
    ('o', 14),
    ('p', 15),
]

PLAYER_INDEX_BY_CHAR: typing.Dict[str, int] = {
    'a': 0,
    'b': 1,
    'c': 2,
    'd': 3,
    'e': 4,
    'f': 5,
    'g': 6,
    'h': 7,
    'i': 8,
    'j': 9,
    'k': 10,
    'l': 11,
    'm': 12,
    'n': 13,
    'o': 14,
    'p': 15,
}

PLAYER_CHAR_BY_INDEX: typing.List[str] = [
    'a',
    'b',
    'c',
    'd',
    'e',
    'f',
    'g',
    'h',
    'i',
    'j',
    'k',
    'l',
    'm',
    'n',
    'o',
    'p',
]


class TileDelta(object):
    __slots__ = (
        'oldArmy',
        'oldOwner',
        'newOwner',
        'gainedSight',
        'lostSight',
        'discovered',
        'imperfectArmyDelta',
        'friendlyCaptured',
        'armyDelta',
        'unexplainedDelta',
        'fromTile',
        'toTile',
        'armyMovedHere',
        'expectedDelta',
        'discoveredExGeneralCity',
    )

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

        self.discoveredExGeneralCity: bool = False
        """True when a tile that wasnt a city (or obstacle) gets discovered as a city. Only true for THAT turn."""

    def __str__(self) -> str:
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

    def __repr__(self) -> str:
        return str(self)

    # def __getstate__(self) -> typing.Dict[str, typing.Any]:
    #     state = self.__dict__.copy()
    #
    #     if self.fromTile is not None:
    #         state["fromTile"] = f'{self.fromTile.x},{self.fromTile.y}:{self.fromTile.tile_index}'
    #     if self.toTile is not None:
    #         state["toTile"] = f'{self.toTile.x},{self.toTile.y}:{self.toTile.tile_index}'
    #     return state

    # def __setstate__(self, state: typing.Dict[str, typing.Any]):
    #     if state['fromTile'] is not None:
    #         x, y = state['fromTile'].split(',')
    #         y, index = y.split(':')
    #         copy = Tile(int(x), int(y))
    #         copy.tile_index = int(index)
    #         state["fromTile"] = copy
    #     if state['toTile'] is not None:
    #         x, y = state['toTile'].split(',')
    #         y, index = y.split(':')
    #         copy = Tile(int(x), int(y))
    #         copy.tile_index = int(index)
    #         state["toTile"] = copy
    #     self.__dict__.update(state)

    # SLOTS VERSION
    def __getstate__(self) -> typing.Dict[str, typing.Any]:
        state = { slot: getattr(self, slot) for slot in self.__slots__ }

        if self.fromTile is not None:
            state["fromTile"] = f'{self.fromTile.x},{self.fromTile.y}:{self.fromTile.tile_index}'
        if self.toTile is not None:
            state["toTile"] = f'{self.toTile.x},{self.toTile.y}:{self.toTile.tile_index}'
        return state

    def __setstate__(self, state: typing.Dict[str, typing.Any]):
        if state['fromTile'] is not None:
            x, y = state['fromTile'].split(',')
            y, index = y.split(':')
            copy = Tile(int(x), int(y))
            copy.tile_index = int(index)
            state["fromTile"] = copy

        if state['toTile'] is not None:
            x, y = state['toTile'].split(',')
            y, index = y.split(':')
            copy = Tile(int(x), int(y))
            copy.tile_index = int(index)
            state["toTile"] = copy

        for slot, val in state.items():
            setattr(self, slot, val)


class Tile(object):
    __slots__ = (
        'x',
        'y',
        'tile',
        'turn_captured',
        'army',
        'isCity',
        'isTempFogPrediction',
        '_player',
        # '_isGeneral',
        'isGeneral',
        'visible',
        'discovered',
        'discoveredAsNeutral',
        'lastSeen',
        'lastMovedTurn',
        'isMountain',
        'delta',
        'adjacents',
        'movable',
        'tile_index',
        '_hash_key',
        'isTelescope',
        'isLookout',
    )

    def __init__(
            self,
            x,
            y,
            tile=TILE_EMPTY,
            army=0,
            isCity=False,
            isGeneral=False,
            player: typing.Union[None, int] = None,
            isMountain=False,
            turnCapped=0,
            tileIndex: int = -1,
            isTelescope=False,
            isLookout=False,
    ):
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

        # self._isGeneral: bool = isGeneral
        # """Boolean isGeneral"""
        self.isGeneral: bool = isGeneral
        """Boolean isGeneral"""

        self.isTempFogPrediction: bool = False

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

        self.isTelescope: bool = isMountain

        self.isLookout: bool = isMountain

        self.delta: TileDelta = TileDelta()
        """Tile's army/player/whatever delta since last turn"""

        self.adjacents: typing.List[Tile] = []
        """Tiles VISIBLE from this tile (not necessarily movable, includes diagonals)"""

        self.movable: typing.List[Tile] = []
        """Tiles movable (left right up down) from this tile, including mountains, cities, obstacles."""

        self.tile_index: int = tileIndex
        self._hash_key = hash((self.x, self.y))

    # # NO SLOTS VERSON
    # def __getstate__(self) -> typing.Dict[str, typing.Any]:
    #     state = self.__dict__.copy()
    #     if "movable" in state:
    #         del state["movable"]
    #     if "adjacents" in state:
    #         del state["adjacents"]
    #     return state
    #
    # def __setstate__(self, state: typing.Dict[str, typing.Any]):
    #     self.__dict__.update(state)
    #     self.movable = []
    #     self.adjacents = []

    # SLOTS VERSION
    def __getstate__(self) -> typing.Dict[str, typing.Any]:
        state = { slot: getattr(self, slot) for slot in self.__slots__ }
        if "movable" in state:
            del state["movable"]
        if "adjacents" in state:
            del state["adjacents"]
        return state

    def __setstate__(self, state: typing.Dict[str, typing.Any]):
        for slot, val in state.items():
            setattr(self, slot, val)

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
    def movableNoObstacles(self) -> typing.Generator[Tile, None, None]:
        for t in self.movable:
            if not t.isObstacle:
                yield t

    @property
    def coords(self) -> typing.Tuple[int, int]:
        """
        NOT high performance, generated on the fly each time.

        @return: (x, y)
        """
        return self.x, self.y

    @property
    def player(self) -> int:
        """int player index"""
        return self._player

    @player.setter
    def player(self, value: int):
        if self.isGeneral and self._player != value and self._player != -1:
            raise AssertionError(f'trying to set general tile {str(self)} player from {self._player} to {value}')

        # TODO why is any of this tile setter shit here at all?
        if value >= 0 and self.visible:
            self.tile = value
        elif value == -1 and self.army == 0 and not self.isNotPathable and not self.isCity and not self.isMountain:
            self.tile = TILE_EMPTY # this whole thing seems wrong, needs to be updated carefully with tests as the delta logic seems to rely on it...

        self._player = value

    # @property
    # def army(self) -> int:
    #     """int army for debugging"""
    #     return self._army
    #
    # @army.setter
    # def army(self, value: int):
    #     self._army = value
    #
    # @property
    # def isGeneral(self) -> bool:
    #     """int isGeneral val for debugging"""
    #     return self._isGeneral
    #
    # @isGeneral.setter
    # def isGeneral(self, value: bool):
    #     self._isGeneral = value

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

    def __str__(self) -> str:
        return f"{self.x},{self.y}"

    def __repr__(self) -> str:
        vRep = self.get_value_representation()

        delta = ''
        if self.delta.armyDelta != 0 or self.delta.unexplainedDelta != 0:
            delta = f' {self.delta.armyDelta}d|{self.delta.unexplainedDelta}u'

        return f"({self.x:d},{self.y:d}) {vRep}{delta}"

    def get_value_representation(self) -> str:
        outputToJoin = []
        if self.player >= 0:
            playerChar = Tile.convert_player_to_char(self.player)
            outputToJoin.append(playerChar)
        if self.isCity:
            outputToJoin.append('C')
        if self.isLookout:
            outputToJoin.append('L')
        elif self.isTelescope:
            outputToJoin.append('T')
        elif self.isMountain or (not self.visible and self.isNotPathable):
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

    def __lt__(self, other: Tile | None):
        if other is None:
            return False
        return self.army < other.army

    def __gt__(self, other: Tile | None):
        if other is None:
            return True
        return self.army > other.army

    def toString(self) -> str:
        return str(self)

    def __hash__(self):
        return self.tile_index
        # return self._hash_key

    def __eq__(self, other):
        if other is None:
            return False
        return self.tile_index == other.tile_index

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
        wasObstacle = self.isObstacle
        if not self.visible:
            self.delta.imperfectArmyDelta = True
        if tile >= TILE_MOUNTAIN:
            self.isTempFogPrediction = False
            if not self.discovered:
                self.discovered = True
                self.delta.discovered = True
                if tile <= TILE_EMPTY:
                    self.discoveredAsNeutral = True
                if self.isGeneral and not isGeneral:
                    self.isGeneral = False
                    if map.generals[self.player] == self:
                        map.generals[self.player] = None
                        map.players[self.player].general = None
                    try:
                        idx = map.generals.index(self)
                        map.generals[idx] = None
                    except:
                        pass
            self.lastSeen = map.turn
            if not self.visible:
                self.delta.gainedSight = True
                self.visible = True

        armyMovedHere = False

        self.delta.oldOwner = self._player

        if self.tile != tile:  # tile changed
            if tile < TILE_MOUNTAIN and self.discovered and not tile == TILE_LOOKOUT and not tile == TILE_TELESCOPE:  # lost sight of tile.
                if self.visible:
                    self.delta.lostSight = True
                self.visible = False
                self.lastSeen = map.turn - 1

                if self._player == map.player_index or self._player in map.teammates:
                    # we lost the tile
                    # I think this is handled by the Fog Island handler during map update...?
                    self.delta.friendlyCaptured = True
                    logbook.info(f'tile captured, losing vision, army moved here true for {str(self)}')
                    armyMovedHere = True
                    self._player = -1
                elif self._player >= 0 and self.army > 1:
                    # we lost SIGHT of enemy tile, IF this tile has positive army, then army could have come from here TO another tile.
                    logbook.info(f'enemy tile adjacent to vision lost was lost, army moved here true for {str(self)}')  # TODO
                    # armyMovedHere = True
            elif tile >= TILE_EMPTY:
                self._player = tile

            self.tile = tile

        if tile in MOUNTAIN_TILES:
            if not self.isMountain:
                for movableTile in self.movable:
                    if self in movableTile.movable:
                        movableTile.movable.remove(self)

                self.isMountain = True
            if tile == TILE_LOOKOUT:
                self.isLookout = True
            elif tile == TILE_TELESCOPE:
                self.isTelescope = True

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
            # logbook.info("assigning tile {} with oldArmy {} new army {}?".format(self.toString(), oldArmy, army))
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
            if not wasObstacle:
                self.delta.discoveredExGeneralCity = True

        elif isGeneral:
            playerObj = map.players[self._player]
            playerObj.general = self
            self.isGeneral = True

        if self.delta.oldOwner != self.delta.newOwner:
            # logbook.debug(f'oldOwner != newOwner for {str(self)}')
            armyMovedHere = True

        # if self.delta.oldOwner == self.delta.newOwner and self.delta.armyDelta == 0:
        #     armyMovedHere = False

        if tile in MOUNTAIN_TILES or (tile == TILE_EMPTY and isCity and self.delta.gainedSight):
            armyMovedHere = False
            if tile in MOUNTAIN_TILES or army > 38:
                self.delta.imperfectArmyDelta = False
                self.delta.armyDelta = 0
                self.delta.unexplainedDelta = 0

        self.delta.armyMovedHere = armyMovedHere

        if armyMovedHere:
            # logbook.debug(f'armyMovedHere True for {str(self)} (expected delta was {self.delta.expectedDelta}, actual was {self.delta.armyDelta})')
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
        self.isTempFogPrediction = False
        self.army = 0
        self._player = -1
        self.isGeneral = False
        self.delta = TileDelta()

    @classmethod
    def get_move_half_amount(cls, army: int) -> int:
        """This is the amount of army that will leave the tile, not the amount that will be left on the tile."""
        return army // 2

