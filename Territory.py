"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    April 2017
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""

import logbook
import time
import json

import SearchUtils
from SearchUtils import *
from test.test_float import INF

from base.client.map import new_map_grid


# attempts to classify tiles into territories.
class TerritoryClassifier(object):
    def __init__(self, map: MapBase):
        self.map: MapBase = map
        self.lastCalculatedTurn = -1
        self.territoryMap: MapMatrixInterface[int] = MapMatrix(self.map, -1)
        self.needToUpdateAroundTiles = set()
        self.team_indexes: typing.List[int] = list(set(MapBase.get_teams_array(self.map)))
        self.territoryDistances: typing.List[MapMatrixInterface[int]] = [MapMatrix(map, 1000) for p in map.players]
        self.territoryTeamDistances: typing.List[MapMatrixInterface[int]] = [MapMatrix(map, 1000) for p in self.team_indexes]
        for tile in self.map.pathable_tiles:
            self.needToUpdateAroundTiles.add(tile)

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def should_recalculate(self, turn):
        if len(self.needToUpdateAroundTiles) > 0:
            return True
        return False

    def revealed_tile(self, tile):
        """
        When a tile is initially discovered, it should be used to weight territories as the player
        it was discovered as (to prevent the creep of neutral weighted discovery).
        Note that this gets immediately overwritten by the actual territory value for this tile,
        it is just used to weight the tiles around it during that cycle.
        """
        self.territoryMap[tile] = tile.player
        if tile.player != -1 and tile.player != self.map.player_index:
            for movable in tile.movable:
                if not movable.discovered and not movable.isObstacle:
                    self.territoryMap[movable] = tile.player

    def scan(self):
        logbook.info("Scanning map for territories, aww geez")
        counts = new_map_grid(self.map, lambda x, y: [0 for n in range(len(self.map.players) + 1)])
        startTime = time.perf_counter()
        undiscoveredCounterDepth = 5
        # count the number of tiles for each player within range 3 to determine whose territory this is
        neutralNewIndex = len(self.map.players)
        
        # do a BFS foreach within a BFS foreach. Normal everyday stuff nbd
        def foreach_near_updated_tiles(evaluatingTile: Tile):
            if evaluatingTile.player != -1 and evaluatingTile.player != self.map.player_index:  # and not evaluatingTile.discoveredAsNeutral (territories track live territory, not general prediction)
                for movable in evaluatingTile.movable:
                    if not movable.discovered and not movable.isObstacle:
                        self.territoryMap[movable] = evaluatingTile.player
                        counts[evaluatingTile.x][evaluatingTile.y][evaluatingTile.player] += 3
                        counts[movable.x][movable.y][evaluatingTile.player] += 5

            def countFunc(tile):
                if tile.isObstacle:
                    return tile.player == -1 and tile.discovered
                
                currentTerritory = self.territoryMap[tile]
                if not evaluatingTile.discovered:
                    # weight based on territory already owned, making it harder to flip a territory (and hopefully better encapsulate who owns what)
                    if currentTerritory != -1:
                        # do NOT allow our player to own undiscovered territory. If owned by us, is neutral.
                        # This prevents the undiscovered-tile-friendly-territory cascade from happening.
                        if tile.discovered and not evaluatingTile.discovered and currentTerritory != self.map.player_index:
                            counts[evaluatingTile.x][evaluatingTile.y][currentTerritory] += 0.3
                        elif currentTerritory == self.map.player_index:
                            counts[evaluatingTile.x][evaluatingTile.y][neutralNewIndex] += 0.06
                    else:
                        # only discovered neutral tiles count, and only if we're trying to classify a neutral tile.
                        counts[evaluatingTile.x][evaluatingTile.y][neutralNewIndex] += 0.014
                else:
                    # undiscovereds count for the evaluating tile player
                    if not tile.discovered:
                        counts[evaluatingTile.x][evaluatingTile.y][evaluatingTile.player] += 0.25
                    else:
                        pIndex = tile.player
                        if pIndex != -1 and pIndex != self.map.player_index:
                            counts[evaluatingTile.x][evaluatingTile.y][pIndex] += 1
                        elif pIndex != -1: 
                            # weight our tiles less because we see more of them.
                            counts[evaluatingTile.x][evaluatingTile.y][pIndex] += 0.8

                return tile.player == -1 and tile.discovered

            breadth_first_foreach(self.map, [evaluatingTile], undiscoveredCounterDepth, countFunc, noLog = True)
            maxPlayer = -1
            maxValue = 0
            for pIndex, value in enumerate(counts[evaluatingTile.x][evaluatingTile.y]):
                if value > maxValue:
                    maxPlayer = pIndex
                    maxValue = value
            userName = "Neutral"
                
            # convert back to -1 index for neutral
            if maxPlayer == neutralNewIndex:
                maxPlayer = -1
            else:
                userName = self.map.usernames[maxPlayer]

            if evaluatingTile.player != maxPlayer and evaluatingTile.player != -1:
                logbook.info("Tile {} is in player {} {} territory".format(evaluatingTile.toString(), maxPlayer, userName))

            self.territoryMap[evaluatingTile] = maxPlayer

            return evaluatingTile.isMountain

        startTiles = list(self.needToUpdateAroundTiles)
        logbook.info("  Scanning territory around {}".format(" - ".join([tile.toString() for tile in startTiles])))
        breadth_first_foreach(self.map, startTiles, undiscoveredCounterDepth, foreach_near_updated_tiles)
        duration = time.perf_counter() - startTime
            
        logbook.info("Completed scanning territories in {:.3f}".format(duration))
        self.needToUpdateAroundTiles = set()

        for player in self.map.players:
            if player.dead:
                continue

            startTiles = []
            for tile in self.map.get_all_tiles():
                if self.territoryMap[tile] == player.index:
                    startTiles.append(tile)

            self.territoryDistances[player.index] = SearchUtils.build_distance_map_matrix(self.map, startTiles)

        for team in self.team_indexes:
            startTiles = []
            for tile in self.map.pathable_tiles:
                if self.map.is_player_on_team(self.territoryMap[tile], team):
                    startTiles.append(tile)

            self.territoryTeamDistances[team] = SearchUtils.build_distance_map_matrix(self.map, startTiles)

    def is_tile_in_friendly_territory(self, tile: Tile) -> bool:
        """Returns False if tile is in neutral or enemy territory. True only for player territory."""
        territory = self.get_tile_territory(tile)
        if territory == -1:
            return False

        return self.map.is_player_on_team_with(territory, self.map.player_index)

    def is_tile_in_enemy_territory(self, tile: Tile) -> bool:
        """Returns True if the tile is not in neutral or friendly territory."""

        territory = self.get_tile_territory(tile)
        return territory >= 0 and not self.map.is_player_on_team_with(territory, self.map.player_index)

    def is_tile_in_player_territory(self, tile: Tile, player: int) -> bool:
        """Returns True if the tile is not in neutral territory and is in the territory of the specified player."""

        territory = self.get_tile_territory(tile)
        return self.map.is_player_on_team_with(territory, player)

    def get_tile_territory(self, tile: Tile) -> int:
        return self.territoryMap[tile]