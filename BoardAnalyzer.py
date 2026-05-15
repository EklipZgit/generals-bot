"""
    @ Travis Drake (EklipZ) eklipz.io - tdrake0x45 at gmail)
    July 2019
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    EklipZ bot - Tries to play generals lol
"""
import time
import typing
from collections import deque
from dataclasses import dataclass

import logbook

import SearchUtils
from ArmyAnalyzer import ArmyAnalyzer
from Models import Move
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet
from base.client.map import MapBase, Tile


@dataclass(slots=True)
class DefensiveChokePoint:
    defended_tile: Tile
    x: float
    y: float
    distance_from_source: int
    choke_tiles: typing.List[Tile]


class BoardAnalyzer:
    def __init__(self, map: MapBase, general: Tile, teammateGeneral: Tile | None = None):
        startTime = time.perf_counter()
        self.map: MapBase = map
        self.general: Tile = general
        self.teammate_general: Tile | None = teammateGeneral
        self.should_rescan = True

        # TODO probably calc these chokes for the enemy, too?
        self.innerChokes: MapMatrixSet = MapMatrixSet(map)
        """Tiles that only have one outward path away from our general."""

        self.outerChokes: MapMatrixSet = MapMatrixSet(map)
        """Tiles that only have a single inward path towards our general."""

        self.central_defense_point: Tile = map.players[map.player_index].general

        self.defensive_chokes_by_tile: typing.Dict[Tile, DefensiveChokePoint] = {}
        self.defensive_furthest_choke_tiles_by_defensive_tile: typing.Dict[Tile, typing.Set[Tile]] = {}

        self.friendly_city_distances: typing.Dict[Tile, MapMatrixInterface[int]] = {}

        self.defense_centrality_sums: MapMatrixInterface[int] = MapMatrix(self.map, initVal=250)

        self.intergeneral_analysis: ArmyAnalyzer = None

        self.core_play_area_matrix: MapMatrixSet = None

        self.extended_play_area_matrix: MapMatrixSet = None

        self.shortest_path_distances: MapMatrixInterface[int] = None

        self.flankable_fog_area_matrix: MapMatrixSet = None
        """
        Fog tiles that are potentially reachable from the opponent, and thus could be a flank source
        """

        self.flank_danger_play_area_matrix: MapMatrixSet = None
        """
        All tiles that are within the flank danger distance, visible or not
        """

        self.backwards_tiles: typing.Set[Tile] = set()

        self.general_distances: MapMatrixInterface[int] = MapMatrix(self.map)

        self.all_possible_enemy_spawns: typing.Set[Tile] = set()

        self.friendly_general_distances: MapMatrixInterface[int] = MapMatrix(self.map)
        """The distance map to any friendly general."""

        self.teammate_distances: MapMatrixInterface[int] = MapMatrix(self.map)

        self.inter_general_distance: int = 10
        """The (possibly estimated) distance between our gen and target player gen."""

        self.within_core_play_area_threshold: int = 1
        """The cutoff point where we draw pink borders as the 'core' play area between generals."""

        self.within_extended_play_area_threshold: int = 2
        """The cutoff point where we draw yellow borders as the 'extended' play area between generals."""

        self.within_flank_danger_play_area_threshold: int = 4
        """The cutoff point where we draw red borders as the flank danger surface area."""

        self.enemy_wall_breach_scores: MapMatrixInterface[int] = MapMatrix(map, None)

        self.friendly_wall_breach_scores: MapMatrixInterface[int] = MapMatrix(map, None)

        self.rescan_chokes()

    def __getstate__(self):
        state = self.__dict__.copy()
        if "map" in state:
            del state["map"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.map = None

    def rescan_chokes(self, cities_in_play: typing.Set[Tile] | None = None):
        self.should_rescan = False

        oldInner = self.innerChokes
        oldOuter = self.outerChokes
        self.innerChokes = MapMatrixSet(self.map)

        self.outerChokes = MapMatrixSet(self.map)
        cities = list(self.map.players[self.map.player_index].cities)

        self.general_distances = self.map.distance_mapper.get_tile_dist_matrix(self.general)
        if self.teammate_general is not None and self.teammate_general.player in self.map.teammates:
            self.teammate_distances = self.map.distance_mapper.get_tile_dist_matrix(self.teammate_general)
            self.friendly_general_distances = SearchUtils.build_distance_map_matrix(self.map, [self.teammate_general, self.general])
            cities.extend(self.map.players[self.teammate_general.player].cities)
        else:
            self.friendly_general_distances = self.general_distances

        # Use cities_in_play if provided, filtering to only include cities we own or teammate owns
        if cities_in_play is not None:
            friendlyCitiesInPlay = [c for c in cities_in_play if c.player == self.general.player or (self.teammate_general is not None and c.player == self.teammate_general.player)]
            if friendlyCitiesInPlay:
                cities = friendlyCitiesInPlay

        closestCities = cities
        if self.intergeneral_analysis is not None:
            # only consider the closest 3 cities to enemy...?
            closestCities = list(sorted(cities, key=lambda c: self.intergeneral_analysis.bMap[c]))[0:3]
        logbook.info(
            'CENTRAL_DEFENSE_POINT defended tiles considered: '
            + f'general {str(self.general)} enemyDist={self.intergeneral_analysis.bMap.raw[self.general.tile_index] if self.intergeneral_analysis is not None else None}'
            + ' cities '
            + ' | '.join(
                [
                    f'{str(city)} enemyDist={self.intergeneral_analysis.bMap.raw[city.tile_index] if self.intergeneral_analysis is not None else None} friendlyDist={self.general_distances.raw[city.tile_index]} player={city.player} army={city.army}'
                    for city in closestCities
                ]))

        self.friendly_city_distances = {}
        for city in closestCities:
            self.friendly_city_distances[city] = self.map.distance_mapper.get_tile_dist_matrix(city)
        for tile in self.map.pathable_tiles:
            tileDist = self.friendly_general_distances.raw[tile.tile_index]
            movableInnerCount = SearchUtils.count(tile.movable, lambda adj: tileDist == self.friendly_general_distances.raw[adj.tile_index] - 1)
            movableOuterCount = SearchUtils.count(tile.movable, lambda adj: tileDist == self.friendly_general_distances.raw[adj.tile_index] + 1)
            if movableInnerCount == 1:
                self.outerChokes.raw[tile.tile_index] = True
            # checking movableInner to avoid considering dead ends 'chokes'
            if (
                    movableOuterCount == 1
                    # and movableInnerCount >= 1
            ):
                self.innerChokes.raw[tile.tile_index] = True
            if self.map.turn > 4:
                if oldInner.raw[tile.tile_index] != self.innerChokes.raw[tile.tile_index]:
                    logbook.info(
                        f"  inner choke change: tile {str(tile)}, old {oldInner.raw[tile.tile_index]}, new {self.innerChokes.raw[tile.tile_index]}")
                if oldOuter.raw[tile.tile_index] != self.outerChokes.raw[tile.tile_index]:
                    logbook.info(
                        f"  outer choke change: tile {str(tile)}, old {oldOuter.raw[tile.tile_index]}, new {self.outerChokes.raw[tile.tile_index]}")

    def _get_defensive_choke_point(self, defendedTile: Tile) -> DefensiveChokePoint:
        if self.intergeneral_analysis is None:
            chokePoint = DefensiveChokePoint(
                defended_tile=defendedTile,
                x=defendedTile.x,
                y=defendedTile.y,
                distance_from_source=0,
                choke_tiles=[defendedTile])
            self.defensive_chokes_by_tile[defendedTile] = chokePoint
            self.defensive_furthest_choke_tiles_by_defensive_tile[defendedTile] = {defendedTile}
            return chokePoint

        enemyDistMap = self.intergeneral_analysis.bMap
        baseLength = enemyDistMap.raw[defendedTile.tile_index]
        startTiles = self._get_defensive_choke_start_tiles(defendedTile, baseLength)
        layers = self._build_defensive_choke_layers(startTiles, baseLength)
        logbook.info(
            f'GET_DEF_CHOKE {defendedTile} baseLength={baseLength} startTiles=\r\n  start: '
            + '\r\n  start: '.join(self._defensive_choke_tile_to_string(tile) for tile in startTiles))
        # self._log_defensive_choke_layers(defendedTile, layers)

        bestDistance = 0
        bestLayer = [defendedTile]
        for distance in range(len(layers) - 1, -1, -1):
            layerTiles = layers[distance]
            visible = self._are_tiles_visible(layerTiles)
            contiguous = self._are_tiles_contiguous(layerTiles)
            if visible and contiguous:
                bestDistance = distance
                bestLayer = layerTiles
                break
            # logbook.info(
            #     f'  GET_DEF_CHOKE {defendedTile} rejected layer defended={str(defendedTile)} distance={distance} visible={visible} contiguous={contiguous} tiles=\r\n    '
            #     + '\r\n    '.join(self._defensive_choke_tile_to_string(tile) for tile in layerTiles))

        chokePoint = DefensiveChokePoint(
            defended_tile=defendedTile,
            x=sum(tile.x for tile in bestLayer) / len(bestLayer),
            y=sum(tile.y for tile in bestLayer) / len(bestLayer),
            distance_from_source=bestDistance,
            choke_tiles=bestLayer)
        self.defensive_chokes_by_tile[defendedTile] = chokePoint
        self.defensive_furthest_choke_tiles_by_defensive_tile[defendedTile] = set(bestLayer)
        logbook.info(
            f'GET_DEF_CHOKE {defendedTile} selected choke position {self._defensive_choke_point_to_string(chokePoint)} for {str(defendedTile)} baseLength={baseLength} startTiles={len(startTiles)} layerTiles=\r\n{"\r\n".join(str(tile) for tile in bestLayer)}')
        return chokePoint

    def _get_defensive_choke_start_tiles(self, defendedTile: Tile, baseLength: int) -> typing.List[Tile]:
        startTiles: typing.List[Tile] = []
        q = deque([(defendedTile, 0)])
        visited = {defendedTile.tile_index}
        enemyDistMap = self.intergeneral_analysis.bMap

        while q:
            tile, dist = q.popleft()
            if dist > 2:
                continue

            enemyDist = enemyDistMap.raw[tile.tile_index]
            if enemyDist >= baseLength and tile.visible and not tile.isObstacle:
                startTiles.append(tile)

            if dist == 2:
                continue

            for nextTile in tile.movable:
                if nextTile.tile_index in visited:
                    continue
                visited.add(nextTile.tile_index)
                q.append((nextTile, dist + 1))

        if not startTiles:
            startTiles.append(defendedTile)

        return startTiles

    def _build_defensive_choke_layers(self, startTiles: typing.List[Tile], baseLength: int) -> typing.List[typing.List[Tile]]:
        q = deque((tile, 0) for tile in startTiles)
        visited = {tile.tile_index for tile in startTiles}
        layers: typing.List[typing.List[Tile]] = []
        enemyDistMap = self.intergeneral_analysis.bMap

        while q:
            tile, dist = q.popleft()
            if tile.isObstacle:
                continue

            enemyDist = enemyDistMap.raw[tile.tile_index]
            while len(layers) <= dist:
                layers.append([])
            layers[dist].append(tile)
            if not tile.visible:
                continue

            for nextTile in tile.movable:
                if nextTile.tile_index in visited:
                    continue
                if nextTile.isObstacle:
                    continue
                nextEnemyDist = enemyDistMap.raw[nextTile.tile_index]
                if nextEnemyDist > enemyDist:
                    continue
                visited.add(nextTile.tile_index)
                q.append((nextTile, dist + 1))

        return layers

    def _are_tiles_visible(self, tiles: typing.List[Tile]) -> bool:
        return all(tile.visible for tile in tiles)

    def _are_tiles_contiguous(self, tiles: typing.List[Tile]) -> bool:
        if len(tiles) <= 1:
            return True

        tileIndexes = {tile.tile_index for tile in tiles}
        visited = {tiles[0].tile_index}
        q = deque([tiles[0]])

        while q:
            tile = q.popleft()
            for nextTile in tile.movable:
                if nextTile.tile_index not in tileIndexes:
                    continue
                if nextTile.tile_index in visited:
                    continue
                visited.add(nextTile.tile_index)
                q.append(nextTile)

        return len(visited) == len(tileIndexes)

    def _get_distance_to_defensive_choke_point(self, tile: Tile, chokePoint: DefensiveChokePoint) -> float:
        return abs(tile.x - chokePoint.x) + abs(tile.y - chokePoint.y)

    def _defensive_choke_point_to_string(self, chokePoint: DefensiveChokePoint) -> str:
        return f'{chokePoint.x:.2f},{chokePoint.y:.2f}/d{chokePoint.distance_from_source}'

    def _defensive_choke_tile_to_string(self, tile: Tile) -> str:
        enemyDist = self.intergeneral_analysis.bMap.raw[tile.tile_index] if self.intergeneral_analysis is not None else None
        friendlyDist = self.friendly_general_distances.raw[tile.tile_index] if self.friendly_general_distances is not None else None
        return f'{str(tile)} e{enemyDist} f{friendlyDist} vis={tile.visible} disc={tile.discovered} p{tile.player} a{tile.army}'

    def _log_defensive_choke_layers(self, defendedTile: Tile, layers: typing.List[typing.List[Tile]]):
        for distance, layerTiles in enumerate(layers):
            visible = self._are_tiles_visible(layerTiles)
            contiguous = self._are_tiles_contiguous(layerTiles)
            logbook.info(
                f'CENTRAL_DEFENSE_POINT layer defended={str(defendedTile)} distance={distance} count={len(layerTiles)} visible={visible} contiguous={contiguous} tiles=\r\n  '
                + '\r\n  '.join(self._defensive_choke_tile_to_string(tile) for tile in layerTiles))

    def rebuild_intergeneral_analysis(self, opponentGeneral: Tile, possibleSpawns: typing.List[MapMatrixSet] | None = None, cities_in_play: typing.Set[Tile] | None = None):
        self.intergeneral_analysis = ArmyAnalyzer(self.map, self.general, opponentGeneral)

        self.enemy_wall_breach_scores = MapMatrix(self.map, None)
        self.friendly_wall_breach_scores = MapMatrix(self.map, None)
        enemyDistMap = self.intergeneral_analysis.bMap
        generalDistMap = self.intergeneral_analysis.aMap
        general = self.general

        self.inter_general_distance = enemyDistMap[general]

        if possibleSpawns is not None:
            self.rescan_useful_fog(possibleSpawns)

        # if len(self.all_possible_enemy_spawns) < 40 and not opponentGeneral.isGeneral:
        #     enemyDistMap = SearchUtils.build_distance_map(self.map, list(self.all_possible_enemy_spawns))
        #
        #     self.inter_general_distance = enemyDistMap[general]

        self.within_core_play_area_threshold: int = int((self.inter_general_distance + 1) * 1.1)
        self.within_extended_play_area_threshold: int = int((self.inter_general_distance + 2) * 1.2)
        self.within_flank_danger_play_area_threshold: int = int((self.inter_general_distance + 3) * 1.4)
        logbook.info(f'BOARD ANALYSIS THRESHOLDS:\r\n'
                     f'     board shortest dist: {self.inter_general_distance}\r\n'
                     f'     core area dist: {self.within_core_play_area_threshold}\r\n'
                     f'     extended area dist: {self.within_extended_play_area_threshold}\r\n'
                     f'     flank danger dist: {self.within_flank_danger_play_area_threshold}')

        self.core_play_area_matrix: MapMatrixSet = MapMatrixSet(self.map)
        self.extended_play_area_matrix: MapMatrixSet = MapMatrixSet(self.map)
        self.flank_danger_play_area_matrix: MapMatrixSet = MapMatrixSet(self.map)

        self.build_play_area_matrices(enemyDistMap, generalDistMap)

        self.rescan_chokes(cities_in_play)

    def build_play_area_matrices(self, enemyDistMap: MapMatrixInterface[int], generalDistMap: MapMatrixInterface[int]):
        self.backwards_tiles: typing.Set[Tile] = set()
        shortestPathDist = self.intergeneral_analysis.shortestPathWay.distance
        # flankTiles = []
        friendlies = self.map.get_teammates(self.general.player)

        if len(self.intergeneral_analysis.shortestPathWay.tiles) > 0:
            self.shortest_path_distances = SearchUtils.build_distance_map_matrix(
                self.map,
                self.intergeneral_analysis.shortestPathWay.tiles)
        else:
            self.shortest_path_distances = SearchUtils.build_distance_map_matrix(self.map, [self.general])

        for tile in self.map.reachable_tiles:
            tIndex = tile.tile_index
            if tile.isObstacle and not tile.isMountain:
                self.enemy_wall_breach_scores.raw[tIndex] = self._get_wall_breach_score_enemy(tile)
                self.friendly_wall_breach_scores.raw[tIndex] = self._get_wall_breach_score_friendly(tile)

            if not tile.isPathable:  # so we include neutral cities
                continue

            enDist = enemyDistMap.raw[tIndex]
            frDist = generalDistMap.raw[tIndex]
            pathwayDist = enDist + frDist

            # pathWay = self.intergeneral_analysis.pathWayLookupMatrix.raw[tIndex]
            # if pathWay is not None:
            #     pwDist = pathWay.distance - shortestPathDist
            #     self.shortest_path_distances.raw[tIndex] = pwDist
            #     if pwDist != tileDistSum - shortestPathDist:
            #         raise AssertionError(f'tile {tile} - pwDist was {pwDist}, tileDistSum was {tileDistSum} (shortestPathDist {shortestPathDist})')
            #
            # else:
            #     logbook.info(f'DEBUG DEBUG DEBUG {tile} HAD NONE PATHWAY')

            if pathwayDist < self.within_extended_play_area_threshold:
                self.extended_play_area_matrix.raw[tIndex] = True

            if pathwayDist < self.within_core_play_area_threshold:
                self.core_play_area_matrix.raw[tIndex] = True

            if (
                    pathwayDist <= self.within_flank_danger_play_area_threshold
                    # and tileDistSum > self.within_core_play_area_threshold
                    and frDist / (enDist + 1) < 0.7  # prevent us from considering tiles more than 2/3rds into enemy territory as flank danger
            ):
                self.flank_danger_play_area_matrix.raw[tIndex] = True

            if tile.player in friendlies:
                # distToShortestPath = (pathwayDist - shortestPathDist) // 2
                trueShortest = self.shortest_path_distances.raw[tile.tile_index]
                sumThing = enDist - shortestPathDist + trueShortest
                if sumThing > 0:
                    self.backwards_tiles.add(tile)
                # if tile.coords in [(15, 6), (12, 9), (16, 8), (17, 9), (14, 16), (16, 13)]:
                #     logbook.info(f'tile {tile} | {sumThing}; tileDistSum {pathwayDist}, enDist {enDist}, shortestPathDist {shortestPathDist}, pwDist {pathwayDist}, distToShortest, {distToShortestPath}, trueShortest, {trueShortest}')
                # # if sumThing > 0:
                # #     pass

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
        for move in leafMoves:
            # sometimes these might be cut off by only being routed through the general
            neutralCity = (move.dest.isCity and move.dest.player == -1)
            if not neutralCity and self.intergeneral_analysis.pathWayLookupMatrix.raw[move.dest.tile_index] is not None and self.intergeneral_analysis.pathWayLookupMatrix.raw[move.source.tile_index] is not None:
                pathwaySource = self.intergeneral_analysis.pathWayLookupMatrix.raw[move.source.tile_index]
                pathwayDest = self.intergeneral_analysis.pathWayLookupMatrix.raw[move.dest.tile_index]
                if pathwaySource.distance <= maxAltLength:
                    if pathwaySource.distance > pathwayDest.distance or pathwaySource.distance == pathwayDest.distance:
                        # moving to a shorter path or moving along same distance path
                        # If getting further from our general (and by extension closer to opp since distance is equal)
                        gettingFurtherFromOurGen = self.intergeneral_analysis.aMap.raw[move.source.tile_index] < self.intergeneral_analysis.aMap.raw[move.dest.tile_index]
                        # not more than cutoffDist tiles behind our general, effectively

                        reasonablyCloseToTheirGeneral = self.intergeneral_analysis.bMap.raw[move.dest.tile_index] < cutoffDist + self.intergeneral_analysis.aMap.raw[self.intergeneral_analysis.tileB.tile_index]

                        if gettingFurtherFromOurGen and reasonablyCloseToTheirGeneral:
                            goodLeaves.append(move)
                    else:
                        logbook.info(f"Pathway for tile {str(move.source)} was already included, skipping")

        return goodLeaves

    def rescan_useful_fog(self, possibleSpawns: typing.List[MapMatrixSet]):
        self.flankable_fog_area_matrix = MapMatrix(self.map, False)

        enPlayers = SearchUtils.where(self.map.players, lambda p: not self.map.is_player_on_team_with(self.general.player, p.index) and not p.dead)

        startTiles = set()
        hasPerfectInfo = True
        for p in enPlayers:
            if SearchUtils.count(p.cities, lambda c: c.discovered) + 1 < p.cityCount:
                hasPerfectInfo = False
        indexes = [p.index for p in enPlayers]
        for t in self.map.reachable_tiles:
            if t.visible:
                continue

            for player in indexes:
                if possibleSpawns[player].raw[t.tile_index]:
                    startTiles.add(t)

        self.all_possible_enemy_spawns = startTiles
        startList = list(startTiles)
        # dists = SearchUtils.build_distance_map(self.map, startList)
        discountVisibleNearEnemyGen = SearchUtils.Counter(int(self.inter_general_distance * 0.35))

        def foreachFunc(tile: Tile, dist: int) -> bool:
            countsForFlankable = not tile.visible or dist < discountVisibleNearEnemyGen.value
            if hasPerfectInfo and tile.isObstacle:
                return True
            if not countsForFlankable:
                return True
            if tile.isMountain or (tile.isNeutral and tile.isCity and tile.visible):
                return True

            self.flankable_fog_area_matrix.raw[tile.tile_index] = True

        SearchUtils.breadth_first_foreach_dist_fast_no_default_skip(self.map, [self.intergeneral_analysis.tileB], int(self.inter_general_distance * 1.4), foreachFunc)

        discountVisibleNearEnemyGen.value = 0
        SearchUtils.breadth_first_foreach_dist_fast_no_default_skip(self.map, startList, int(self.inter_general_distance * 1.2), foreachFunc)

    def get_wall_breach_expandability(self, tile: Tile, asPlayer: int) -> int:
        if not tile.isObstacle:
            return 0
        enScore = self.enemy_wall_breach_scores[tile]
        frScore = self.friendly_wall_breach_scores[tile]
        if enScore is None or frScore is None:
            return 0

        if self.map.is_tile_on_team_with(self.intergeneral_analysis.tileB, asPlayer):
            return enScore - frScore
        elif self.map.is_tile_on_team_with(self.intergeneral_analysis.tileA, asPlayer):
            return frScore - enScore

        return 0

    def _get_wall_breach_score_combined(self, tile: Tile) -> int:
        """
        Gets the wall breach score from the enemies perspective of decreasing their distances, subtracting the score that it decreases from our general (enemies prefer cities that open up their land, but dont open up our attack path).

        @param tile:
        @return:
        """
        return self._get_wall_breach_score_enemy(tile) + self._get_wall_breach_score_friendly(tile)

    def _get_wall_breach_score_enemy(self, tile: Tile) -> int:
        """
        Gets the wall breach score from the enemies perspective of decreasing their distances.
        @param tile:
        @return:
        """
        maxEnSavings = 0
        for adj in tile.movable:
            if adj.isObstacle:
                continue
            for otherAdj in tile.movable:
                if otherAdj.isObstacle:
                    continue
                if otherAdj is adj:
                    continue

                enDistA = self.intergeneral_analysis.bMap[adj]

                enDistB = self.intergeneral_analysis.bMap[otherAdj]

                maxEnSavings = max(maxEnSavings, abs(enDistA - enDistB) - 2)  # -2 because our measured tiles are always 2 apart, so need to decrease by that

        return maxEnSavings

    def _get_wall_breach_score_friendly(self, tile: Tile) -> int:
        """
        Gets the wall breach score from the enemies perspective of decreasing our distances. Useful for anticipating cities the enemy might shortcut through for surprise-kills on our general.
        @param tile:
        @return:
        """
        maxGenSavings = 0
        for adj in tile.movable:
            if adj.isObstacle:
                continue
            for otherAdj in tile.movable:
                if otherAdj.isObstacle:
                    continue
                if otherAdj is adj:
                    continue

                gDistA = self.intergeneral_analysis.aMap[adj]

                gDistB = self.intergeneral_analysis.aMap[otherAdj]

                maxGenSavings = max(maxGenSavings, abs(gDistA - gDistB) - 2)  # -2 because our measured tiles are always 2 apart, so need to decrease by that

        return maxGenSavings
