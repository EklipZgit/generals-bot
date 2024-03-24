"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    July 2019
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""
import time
import typing

import logbook

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from DataModels import Move
from MapMatrix import MapMatrix
from base.client.map import MapBase, Tile


class BoardAnalyzer:
    def __init__(self, map: MapBase, general: Tile, teammateGeneral: Tile | None = None):
        startTime = time.perf_counter()
        self.map: MapBase = map
        self.general: Tile = general
        self.teammate_general: Tile | None = teammateGeneral
        self.should_rescan = True

        # TODO probably calc these chokes for the enemy, too?
        self.innerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
        """Tiles that only have one outward path away from our general."""

        self.outerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
        """Tiles that only have a single inward path towards our general."""

        self.central_defense_point: Tile = map.players[map.player_index].general

        self.friendly_city_distances: typing.Dict[Tile, MapMatrix[int]] = {}

        self.defense_centrality_sums: MapMatrix[int] = MapMatrix(self.map, initVal=250)

        self.intergeneral_analysis: ArmyAnalyzer = None

        self.core_play_area_matrix: MapMatrix[bool] = None

        self.extended_play_area_matrix: MapMatrix[bool] = None

        self.flankable_fog_area_matrix: MapMatrix[bool] = None

        self.flank_danger_play_area_matrix: MapMatrix[bool] = None

        self.general_distances: typing.List[typing.List[int]] = []

        self.all_possible_enemy_spawns: typing.Set[Tile] = set()

        self.friendly_general_distances: typing.List[typing.List[int]] = []
        """The distance map to any friendly general."""

        self.teammate_distances: typing.List[typing.List[int]] = []

        self.inter_general_distance: int = 10
        """The (possibly estimated) distance between our gen and target player gen."""

        self.within_core_play_area_threshold: int = 1
        """The cutoff point where we draw pink borders as the 'core' play area between generals."""

        self.within_extended_play_area_threshold: int = 2
        """The cutoff point where we draw yellow borders as the 'extended' play area between generals."""

        self.within_flank_danger_play_area_threshold: int = 4
        """The cutoff point where we draw red borders as the flank danger surface area."""

        self.rescan_chokes()

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def rescan_chokes(self):
        self.should_rescan = False
        oldInner = self.innerChokes
        oldOuter = self.outerChokes
        self.innerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]

        self.outerChokes = [[False for x in range(self.map.rows)] for y in range(self.map.cols)]
        cities = list(self.map.players[self.map.player_index].cities)

        self.general_distances = SearchUtils.build_distance_map(self.map, [self.general])
        if self.teammate_general is not None and self.teammate_general.player in self.map.teammates:
            self.teammate_distances = SearchUtils.build_distance_map(self.map, [self.teammate_general])
            self.friendly_general_distances = SearchUtils.build_distance_map(self.map, [self.teammate_general, self.general])
            cities.extend(self.map.players[self.teammate_general.player].cities)
        else:
            self.friendly_general_distances = self.general_distances

        closestCities = cities
        if self.intergeneral_analysis is not None:
            # only consider the closest 3 cities to enemy...?
            closestCities = list(sorted(cities, key=lambda c: self.intergeneral_analysis.bMap[c.x][c.y]))[0:3]

        self.friendly_city_distances = {}
        for city in closestCities:
            self.friendly_city_distances[city] = SearchUtils.build_distance_map_matrix(self.map, [city])
        self.defense_centrality_sums = MapMatrix(self.map, 250)

        lowestAvgDist = 10000000
        lowestAvgTile: Tile | None = None

        for tile in self.map.pathableTiles:
            # logbook.info("Rescanning chokes for {}".format(tile.toString()))
            tileDist = self.friendly_general_distances[tile.x][tile.y]

            distSum = tileDist
            for city, distances in self.friendly_city_distances.items():
                distSum += distances[tile]

            if distSum < lowestAvgDist or (distSum == lowestAvgDist and self.intergeneral_analysis is not None and self.intergeneral_analysis.bMap[tile.x][tile.y] < self.intergeneral_analysis.bMap[lowestAvgTile.x][lowestAvgTile.y]):
                lowestAvgTile = tile
                lowestAvgDist = distSum

            self.defense_centrality_sums[tile] = distSum

            movableInnerCount = SearchUtils.count(tile.movable, lambda adj: tileDist == self.friendly_general_distances[adj.x][adj.y] - 1)
            movableOuterCount = SearchUtils.count(tile.movable, lambda adj: tileDist == self.friendly_general_distances[adj.x][adj.y] + 1)
            if movableInnerCount == 1:
                self.outerChokes[tile.x][tile.y] = True
            # checking movableInner to avoid considering dead ends 'chokes'
            if (movableOuterCount == 1
                    # and movableInnerCount >= 1
            ):
                self.innerChokes[tile.x][tile.y] = True
            if self.map.turn > 4:
                if oldInner[tile.x][tile.y] != self.innerChokes[tile.x][tile.y]:
                    logbook.info(
                        f"  inner choke change: tile {str(tile)}, old {oldInner[tile.x][tile.y]}, new {self.innerChokes[tile.x][tile.y]}")
                if oldOuter[tile.x][tile.y] != self.outerChokes[tile.x][tile.y]:
                    logbook.info(
                        f"  outer choke change: tile {str(tile)}, old {oldOuter[tile.x][tile.y]}, new {self.outerChokes[tile.x][tile.y]}")

        logbook.info(f'calculated central defense point to be {str(lowestAvgTile)} due to lowestAvgDist {lowestAvgDist}')
        self.central_defense_point = lowestAvgTile

    def rebuild_intergeneral_analysis(self, opponentGeneral: Tile, possibleSpawns: typing.List[MapMatrix[bool]]):
        self.intergeneral_analysis = ArmyAnalyzer(self.map, self.general, opponentGeneral)

        enemyDistMap = self.intergeneral_analysis.bMap
        generalDistMap = self.intergeneral_analysis.aMap
        general = self.general

        self.inter_general_distance = enemyDistMap[general.x][general.y]

        if possibleSpawns is not None:
            self.rescan_useful_fog(possibleSpawns)

        # if len(self.all_possible_enemy_spawns) < 40 and not opponentGeneral.isGeneral:
        #     enemyDistMap = SearchUtils.build_distance_map(self.map, list(self.all_possible_enemy_spawns))
        #
        #     self.inter_general_distance = enemyDistMap[general.x][general.y]

        self.within_core_play_area_threshold = int((self.inter_general_distance + 1) * 1.1)
        self.within_extended_play_area_threshold = int((self.inter_general_distance + 2) * 1.2)
        self.within_flank_danger_play_area_threshold = int((self.inter_general_distance + 3) * 1.4)
        logbook.info(f'BOARD ANALYSIS THRESHOLDS:\r\n'
                     f'     board shortest dist: {self.inter_general_distance}\r\n'
                     f'     core area dist: {self.within_core_play_area_threshold}\r\n'
                     f'     extended area dist: {self.within_extended_play_area_threshold}\r\n'
                     f'     flank danger dist: {self.within_flank_danger_play_area_threshold}')

        self.core_play_area_matrix: MapMatrix[bool] = MapMatrix(self.map, initVal=False)
        self.extended_play_area_matrix: MapMatrix[bool] = MapMatrix(self.map, initVal=False)
        self.flank_danger_play_area_matrix: MapMatrix[bool] = MapMatrix(self.map, initVal=False)

        self.build_play_area_matrices(enemyDistMap, generalDistMap)

        self.rescan_chokes()

    def build_play_area_matrices(self, enemyDistMap, generalDistMap):
        for tile in self.map.pathableTiles:
            enDist = enemyDistMap[tile.x][tile.y]
            frDist = generalDistMap[tile.x][tile.y]
            tileDistSum = enDist + frDist
            if tileDistSum < self.within_extended_play_area_threshold:
                self.extended_play_area_matrix[tile] = True

            if tileDistSum < self.within_core_play_area_threshold:
                self.core_play_area_matrix[tile] = True

            if (
                    tileDistSum <= self.within_flank_danger_play_area_threshold
                    # and tileDistSum > self.within_core_play_area_threshold
                    and frDist / (enDist + 1) < 0.7  # prevent us from considering tiles more than 2/3rds into enemy territory as flank danger
            ):
                self.flank_danger_play_area_matrix[tile] = True

    def get_flank_pathways(
            self,
            filter_out_players: typing.List[int] | None = None,
    ) -> typing.Set[Tile]:
        flankDistToCheck = int(self.intergeneral_analysis.shortestPathWay.distance * 1.5)
        flankPathTiles = set()
        for pathway in self.intergeneral_analysis.pathWays:
            if pathway.distance < flankDistToCheck and len(pathway.tiles) >= self.intergeneral_analysis.shortestPathWay.distance:
                for tile in pathway.tiles:
                    if filter_out_players is None or tile.player not in filter_out_players:
                        flankPathTiles.add(tile)

        return flankPathTiles

    # minAltPathCount will force that many paths to be included even if they are greater than maxAltLength
    def find_flank_leaves(
            self,
            leafMoves,
            minAltPathCount,
            maxAltLength
    ) -> typing.List[Move]:
        goodLeaves: typing.List[Move] = []

        # order by: totalDistance, then pick tile by closestToOpponent
        cutoffDist = self.intergeneral_analysis.shortestPathWay.distance // 4
        includedPathways = set()
        for move in leafMoves:
            # sometimes these might be cut off by only being routed through the general
            neutralCity = (move.dest.isCity and move.dest.player == -1)
            if not neutralCity and move.dest in self.intergeneral_analysis.pathWayLookupMatrix and move.source in self.intergeneral_analysis.pathWayLookupMatrix:
                pathwaySource = self.intergeneral_analysis.pathWayLookupMatrix[move.source]
                pathwayDest = self.intergeneral_analysis.pathWayLookupMatrix[move.dest]
                if pathwaySource.distance <= maxAltLength:
                    #if pathwaySource not in includedPathways:
                    if pathwaySource.distance > pathwayDest.distance or pathwaySource.distance == pathwayDest.distance:
                        # moving to a shorter path or moving along same distance path
                        # If getting further from our general (and by extension closer to opp since distance is equal)
                        gettingFurtherFromOurGen = self.intergeneral_analysis.aMap[move.source.x][move.source.y] < self.intergeneral_analysis.aMap[move.dest.x][move.dest.y]
                        # not more than cutoffDist tiles behind our general, effectively

                        reasonablyCloseToTheirGeneral = self.intergeneral_analysis.bMap[move.dest.x][move.dest.y] < cutoffDist + self.intergeneral_analysis.aMap[self.intergeneral_analysis.tileB.x][self.intergeneral_analysis.tileB.y]

                        if gettingFurtherFromOurGen and reasonablyCloseToTheirGeneral:
                            includedPathways.add(pathwaySource)
                            goodLeaves.append(move)
                    else:
                        logbook.info(f"Pathway for tile {str(move.source)} was already included, skipping")

        return goodLeaves

    def rescan_useful_fog(self, possibleSpawns: typing.List[MapMatrix[bool]]):
        self.flankable_fog_area_matrix = MapMatrix(self.map, False)

        enPlayers = SearchUtils.where(self.map.players, lambda p: not self.map.is_player_on_team_with(self.general.player, p.index) and not p.dead)

        startTiles = set()
        indexes = [p.index for p in enPlayers]
        for t in self.map.reachableTiles:
            if t.visible:
                continue

            for player in indexes:
                if possibleSpawns[player][t]:
                    startTiles.add(t)

        self.all_possible_enemy_spawns = startTiles

        def foreachFunc(tile: Tile) -> bool:
            if not tile.visible:
                self.flankable_fog_area_matrix[tile] = True

            return tile.isObstacle or tile.visible

        SearchUtils.breadth_first_foreach(self.map, list(startTiles), int(self.inter_general_distance * 1.2), foreachFunc)
