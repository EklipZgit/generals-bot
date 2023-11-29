from __future__ import annotations

import typing
from enum import Enum


class CycleStatsData:
    def __init__(self, team: int, players: typing.List[int]):
        self.team: int = team
        self.players: typing.List[int] = players

        self.tiles_gained: int = 0
        """Tiles gained (negative if lost) this cycle"""

        self.score_gained: int = 0
        """Score gained (negative if lost) this cycle. Used to track third party opportunities in FFA primarily?"""

        self.cities_gained: int = 0
        """Cities gained this cycle."""

        self.moves_spent_capturing_fog_tiles: int = 0
        """If the players tile count increased but we did not visibly see a move, this gets incremented by one."""

        self.moves_spent_capturing_visible_tiles: int = 0
        """If the player captures a visible tile then we increment this by one. Tracked separate from fog because visible movement obviously wont reduce their fog army approximation."""

        self.moves_spent_gathering_fog_tiles: int = 0
        """If the player has no tile or unexpected score delta visible or otherwise, then this increments by one. Note that this also increments if the player is just afk."""

        self.moves_spent_gathering_visible_tiles: int = 0
        """If the player moves on visible friendly territory, this increments by one."""

        self.approximate_army_gathered_this_cycle: int = 0
        """The expected rough estimate of large tiles (or group of large tiles) gathered by opponent this cycle."""

        self.army_annihilated_visible: int = 0
        """The exact amount of army annihilated for the team from visible moves, assuming we have their city count correct."""

        self.army_annihilated_fog: int = 0
        """The exact amount of army annihilated in the fog for the team, assuming we have their city count correct."""

        self.army_annihilated_total: int = 0
        """The exact amount of army annihilated for the team, assuming we have their city count correct."""

        self.approximate_fog_army_available_total: int = 0
        """The amount of army accumulated for gather emergence from fog, this PLUS fog_city_total should approximate the current risk of size of emergence from any fog flank point."""

        self.approximate_fog_city_army: int = 0
        """The amount of army probably accumulated on cities / generals currently unused. Takes into account the amount of cities they can gather per cycle etc."""

    def clone(self) -> CycleStatsData:
        myClone = CycleStatsData(self.team, self.players)
        myClone.tiles_gained = self.tiles_gained
        myClone.score_gained = self.score_gained
        myClone.cities_gained = self.cities_gained
        myClone.moves_spent_capturing_fog_tiles = self.moves_spent_capturing_fog_tiles
        myClone.moves_spent_capturing_visible_tiles = self.moves_spent_capturing_visible_tiles
        myClone.moves_spent_gathering_fog_tiles = self.moves_spent_gathering_fog_tiles
        myClone.moves_spent_gathering_visible_tiles = self.moves_spent_gathering_visible_tiles
        myClone.approximate_army_gathered_this_cycle = self.approximate_army_gathered_this_cycle
        myClone.army_annihilated_visible = self.army_annihilated_visible
        myClone.army_annihilated_fog = self.army_annihilated_fog
        myClone.army_annihilated_total = self.army_annihilated_total
        myClone.approximate_fog_army_available_total = self.approximate_fog_army_available_total
        myClone.approximate_fog_city_army = self.approximate_fog_city_army
        return myClone

    def __str__(self) -> str:
        return f'g:{self.approximate_army_gathered_this_cycle:3d}  Δt:{self.tiles_gained:2d}  Δc:{self.cities_gained:d}   a:{self.approximate_fog_army_available_total:3d}/c:{self.approximate_fog_city_army:2d}'


class PlayerMoveCategory(Enum):
    FogGather = 1
    FogCapture = 2
    VisibleGather = 3
    VisibleCapture = 4
    Wasted = 5

