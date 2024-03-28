from __future__ import annotations

import itertools
import time
import typing
from collections import deque

import logbook

import SearchUtils
from MapMatrix import MapMatrix, MapMatrixSet
from base.client.map import MapBase, Tile, TeamStats


class TileIsland(object):
    def __init__(self, tiles: typing.Iterable[Tile], team: int, tileCount: int | None = None, armySum: int | None = None):
        self.full_island = None
        if isinstance(tiles, set):
            self.tile_set: typing.Set[Tile] = tiles
        else:
            self.tile_set: typing.Set[Tile] = set(tiles)

        self.team: int = team

        self.tile_count: int = tileCount
        if self.tile_count is None:
            self.tile_count = len(self.tile_set)

        self.sum_army: int = armySum
        if self.sum_army is None:
            self.sum_army = 0
            for t in self.tile_set:
                self.sum_army += t.army

        self.bordered: typing.Set[TileIsland] = set()
        """
        Tile islands that border this island.
        """

        self.tile_count_all_adjacent_friendly: int = self.tile_count
        self.sum_army_all_adjacent_friendly: int = self.sum_army

        # adds about 1/10th of a millisecond to a tile island build
        self.tiles_by_army: typing.List[Tile] = [t for t in sorted(tiles, key=lambda tile: tile.army, reverse=True)]
        self.cities: typing.List[Tile] = [t for t in self.tiles_by_army if t.isCity]

        self.child_islands: typing.List[TileIsland] | None = None
        """
        If this island gets broken up, it will have all its children set here.
        """

        self.full_island: TileIsland | None = None
        """
        If this island is a piece of a broken up full island, this will be set to the original island.
        """

        self.name: str | None = None


class TileIslandBuilder(object):
    def __init__(self, map: MapBase, averageTileIslandSize: int = 8):
        self.map: MapBase = map
        self.teams: typing.List[int] = MapBase.get_teams_array(map)
        # self.expandability_tiles_matrix: MapMatrix[int] = MapMatrix(map, 0)
        # self.expandability_army_matrix: MapMatrix[int] = MapMatrix(map, 0)
        self.tile_island_size: int = averageTileIslandSize
        self.tile_island_split_cutoff: int = int(averageTileIslandSize * 1.5)

        self.tile_island_lookup: MapMatrix[TileIsland] = MapMatrix(self.map, None)
        self.all_tile_islands: typing.List[TileIsland] = []
        self.tile_islands_by_player: typing.List[typing.List[TileIsland]] = [[] for _ in self.map.players]
        self.tile_islands_by_player.append([])  # for -1 player
        self.tile_islands_by_team_id: typing.List[typing.List[TileIsland]] = [[] for _ in self.teams]
        self._team_stats_by_player: typing.List[TeamStats] = []
        self._team_stats_by_team_id: typing.List[TeamStats] = []

    def recalculate_tile_islands(self, enemyGeneralExpectedLocation: Tile | None):  #
        logbook.info('build_tile_islands starting')
        start = time.perf_counter()
        self.tile_island_lookup: MapMatrix[TileIsland] = MapMatrix(self.map, None)
        for teamArray in self.tile_islands_by_player:
            teamArray.clear()
        for teamArray in self.tile_islands_by_team_id:
            teamArray.clear()

        self._team_stats_by_team_id = self.map.get_team_stats_lookup_by_team_id()  # yeah, shut up
        self._team_stats_by_player = [self._team_stats_by_team_id[p.team] for p in self.map.players]
        self._team_stats_by_player.append(self._team_stats_by_team_id[-1])

        newIslands = []

        for tile in self.map.get_all_tiles():
            if tile.isObstacle:
                continue

            existingIsland = self.tile_island_lookup[tile]
            if existingIsland is not None:
                continue

            newIsland = self._build_island_from_tiles([tile], tile.player)
            newIslands.append(newIsland)

        logbook.info(f'initial islands built ({time.perf_counter() - start:.5f}s in)')

        self.all_tile_islands.clear()

        for island in newIslands:
            newIslands = self._break_apart_island_if_too_large(island)

            for newIsland in newIslands:
                self.all_tile_islands.append(newIsland)
                for teammate in self._team_stats_by_team_id[island.team].teamPlayers:
                    self.tile_islands_by_player[teammate].append(newIsland)
                self.tile_islands_by_team_id[newIsland.team].append(newIsland)

        logbook.info(f'building island borders ({time.perf_counter() - start:.5f}s in)')
        for island in self.all_tile_islands:
            # if not island.bordered:
            self._build_island_borders(island)
        complete = time.perf_counter() - start
        logbook.info(f'islands all built in {complete:.5f}s')

    def _build_island_from_tiles(self, startTiles: typing.List[Tile] | typing.Set[Tile], player: int) -> TileIsland:
        tilesInIsland = []
        teammates = self.map.get_teammates(player)
        stats = self._team_stats_by_player[player]

        if len(teammates) > 1:
            def foreachFunc(tile: Tile) -> bool:
                if tile.player in teammates:
                    tilesInIsland.append(tile)

                return tile.player not in teammates
        else:
            def foreachFunc(tile: Tile) -> bool:
                if tile.player == player:
                    tilesInIsland.append(tile)

                return tile.player != player

        SearchUtils.breadth_first_foreach_fast_no_neut_cities(
            self.map,
            startTiles,
            maxDepth=1000,
            foreachFunc=foreachFunc
        )

        island = TileIsland(tilesInIsland, stats.teamId, tileCount=len(tilesInIsland))

        for tile in tilesInIsland:
            self.tile_island_lookup[tile] = island

        return island

    def _build_island_borders(self, island: TileIsland):
        island.bordered.clear()  # in case its already populated. TODO eventually optimize this away if this is at all slow.
        for tile in island.tile_set:
            for movable in tile.movable:
                if movable.isObstacle:
                    continue

                adjIsland = self.tile_island_lookup[movable]
                if adjIsland == island:
                    continue

                island.bordered.add(adjIsland)

    def _break_apart_island_if_too_large(self, island: TileIsland) -> typing.List[TileIsland]:
        stats = self._team_stats_by_team_id[island.team]
        if island.team != -1 and island.tile_count > self.tile_island_split_cutoff:
            # Ok, break the island up.
            island.child_islands = []

            breakIntoSubCount = round(island.tile_count / self.tile_island_size)
            if breakIntoSubCount <= 1:
                return [island]

            # tilesToSplit = island.tile_set.copy()
            brokenByBorders = []

            largestEnemyBorder: TileIsland | None = None
            self._build_island_borders(island)
            # self.tile_island_lookup[]
            for border in island.bordered:
                if border.team == island.team or border.team == -1:
                    continue
                if border.full_island:
                    border = border.full_island

                if largestEnemyBorder is None or largestEnemyBorder.tile_count < border.tile_count:
                    largestEnemyBorder = border

            # distancesFromBorder = SearchUtils.build_distance_map_matrix_include_set(self.map, largestEnemyBorder.tile_set, island.tile_set)
            sets = bifurcate_set_into_n_contiguous(self.map, largestEnemyBorder.tile_set, island.tile_set, breakIntoSubCount)
            logbook.info(f'bifurcated into {len(sets)} sets (desired {breakIntoSubCount}, totalTiles {sum(itertools.chain(len(s.set) for s in sets))})')
            for namedTileSet in sets:
                tileSet = namedTileSet.set
                newIsland = TileIsland(tileSet, island.team)
                newIsland.full_island = island
                newIsland.sum_army_all_adjacent_friendly = island.sum_army_all_adjacent_friendly
                newIsland.tile_count_all_adjacent_friendly = island.tile_count_all_adjacent_friendly
                newIsland.name = namedTileSet.name
                island.child_islands.append(newIsland)

                brokenByBorders.append(newIsland)
                for tile in tileSet:
                    self.tile_island_lookup[tile] = newIsland

            return brokenByBorders
        else:
            return [island]


class SetHolder(object):
    start = 'A'
    end = 'z'
    curLetter = start

    def _get_letter(self):
        ch = SetHolder.curLetter
        if ord(ch) + 1 > ord(SetHolder.end):
            SetHolder.curLetter = SetHolder.start
        else:
            SetHolder.curLetter = chr(ord(ch) + 1)
            while SetHolder.curLetter in ['[', '\\', ']', '^', '_', '`']:
                SetHolder.curLetter = chr(ord(SetHolder.curLetter) + 1)
        return ch

    def __init__(self):
        self.sets: typing.List[typing.Set] = [set()]
        self.length: int = 0
        self.complete: bool = False
        self.name = self._get_letter()
        self.joined_to: SetHolder | None = None

    def join_with(self, other: SetHolder):
        """Other set must be disjoint from this set."""
        self.length += other.length
        self.sets.extend(other.sets)
        other.joined_to = self

    def add(self, item):
        """DOES NOT CHECK FOR DUPLICATES, A DUPLICATE COULD BE IN ANOTHER ENTRY"""
        self.sets[0].add(item)
        self.length += 1

    def __str__(self):
        iterStr = '[]'
        if self.length > 0:
            iterStr = '[' + " | ".join([str(s) for s in itertools.chain.from_iterable(self.sets)]) + ']'
        return f'{self.name}:{self.length} {iterStr}'

    def __repr__(self):
        return str(self)


def _update_set_if_wrong_and_check_already_in_curset(globalVisited, current: Tile, fromTile: Tile) -> bool:
    fromSet = globalVisited[fromTile]
    curSet = globalVisited[current]
    alreadyVisited = curSet is not None
    if fromSet == curSet or not fromSet or not curSet or fromSet.complete or curSet.complete:
        return alreadyVisited

    if fromSet.length < curSet.length:
        # logbook.info(f'executing update_if_wrong FLIPPING {fromTile}->{current} (curSet {curSet.name} <- {fromSet.name})')
        _update_set_if_wrong_and_check_already_in_curset(globalVisited, fromTile, current)
        return True

    # logbook.info(f'executing update_if_wrong {fromTile}->{current} (curSet {curSet.name} -> {fromSet.name})')

    fromSet.join_with(curSet)
    for tile in itertools.chain.from_iterable(curSet.sets):
        globalVisited[tile] = fromSet

    # globalVisited[current] = fromSet

    # for tile in current.movable:
    #     if tile == fromTile:
    #         continue
    #     _update_set_if_wrong_and_check_already_in_curset(globalVisited, tile, current)

    return True


class NamedSet(object):
    def __init__(self, tileSet: typing.Set[Tile], name: str):
        self.name: str = name
        self.set: typing.Set[Tile] = tileSet


def bifurcate_set_into_n_contiguous(
        map: MapBase,
        startPoints: typing.Set[Tile],
        setToBifurcate: typing.Concatenate[typing.Container[Tile],
        typing.Iterable],
        numBreaks: int
) -> typing.List[NamedSet]:
    fullStart = time.perf_counter()

    # Aim to over-break up the tile set so we can recombine back together
    rawBreakThresh = len(setToBifurcate) / numBreaks / 2 - 1
    breakThreshold = max(2, int(rawBreakThresh))

    bifurcationMatrix = MapMatrixSet(map, setToBifurcate)
    buildingNoOptionsTime = 0.0
    fullIterTime = 0.0
    timeInUpdateIfWrongCheck = 0.0
    # tilesWithNoOtherOptions = _get_tiles_with_no_other_options(bifurcationMatrix, setToBifurcate, breakThreshold)

    buildingNoOptionsTime += time.perf_counter() - fullStart
    start = time.perf_counter()

    maxDepth = 1000

    globalVisited: MapMatrix[SetHolder | None] = MapMatrix(map, None)

    frontier = deque()
    allSets = set()
    for tile in startPoints:
        anyInc = False
        for movable in tile.movable:
            if movable not in bifurcationMatrix:
                continue
            anyInc = True
            frontier.appendleft((movable, tile, 0))
        if anyInc:
            fromIsland = SetHolder()
            allSets.add(fromIsland)

    current: Tile
    fromTile: Tile | None
    dist: int
    fromIsland: SetHolder | None = None

    buildingNoOptionsTime += time.perf_counter() - start
    iter = 0
    while frontier:
        iter += 1
        (current, fromTile, dist) = frontier.pop()
        # updateStart = time.perf_counter()
        if _update_set_if_wrong_and_check_already_in_curset(globalVisited, current, fromTile):
            # timeInUpdateIfWrongCheck += time.perf_counter() - updateStart
            continue
        # timeInUpdateIfWrongCheck += time.perf_counter() - updateStart
        if dist > maxDepth:
            break

        # respectComplete = current not in tilesWithNoOtherOptions
        respectComplete = True
        # if not respectComplete:
        #     logbook.info(f'   tilesWithNoOtherOptions contained {current} ({fromTile}->{current}) (deque {len(frontier)})')

        fromIsland = globalVisited[fromTile]
        # if not fromIsland or (fromIsland.complete and respectComplete):
        #     for t in fromTile.movable:
        #         fromIsland = globalVisited[t]
        #         if fromIsland and not (fromIsland.complete and respectComplete):
        #             break

        if not fromIsland or (fromIsland.complete and respectComplete):
            fromIsland = SetHolder()
            # logbook.info(f'new island {fromIsland.name} at {current} ({fromTile}->{current}) (deque {len(frontier)})')
            allSets.add(fromIsland)

        # logbook.info(f'adding {current} to {fromIsland.name} ({fromTile}->{current}) (deque {len(frontier)})')
        fromIsland.add(current)

        globalVisited[current] = fromIsland
        if current.isObstacle:
            continue

        if fromIsland.length >= breakThreshold:
            if not fromIsland.complete:
                fromIsland.complete = True
                # logbook.info(f'marking island {fromIsland.name} complete at length {fromIsland.length}/{breakThreshold}: {fromIsland.name} (deque {len(frontier)})')

        newDist = dist + 1
        for nextTile in current.movable:  # new spots to try
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            if nextTile == fromTile:
                continue
            if nextTile in bifurcationMatrix:
                frontier.appendleft((nextTile, current, newDist))
            # if nextTile in tilesWithNoOtherOptions:
            #     frontier.append((nextTile, current, newDist))
            # elif nextTile in bifurcationMatrix:
            #     frontier.appendleft((nextTile, current, newDist))

    fullIterTime += time.perf_counter() - start
    start = time.perf_counter()

    completedSets = []
    for setHolder in allSets:
        if setHolder.joined_to or setHolder.length == 0:
            continue
        completedSets.append(setHolder)
        # these need to be marked back to incomplete or else we can't join them back up again.
        setHolder.complete = False

    logbook.info(
        f'split {len(setToBifurcate)} tiles into {len(completedSets)} sets of rough size {breakThreshold} in {time.perf_counter() - fullStart:.5f}\r\nRECOMBINING SMALLEST:')

    # join small sets to larger

    finalSets = []
    while len(finalSets) + len(completedSets) > numBreaks and len(completedSets) > 0:
        smallest = min(completedSets, key=lambda s: s.length)

        nextSmallestAdj = None
        smallestTile = None
        nextSmallestAdjTile = None
        for tile in itertools.chain.from_iterable(smallest.sets):
            for t in tile.movable:
                adjSet = globalVisited[t]
                if adjSet is None or adjSet == smallest or adjSet == nextSmallestAdj or adjSet.length == 0:
                    continue

                if nextSmallestAdj is None or nextSmallestAdj.length > adjSet.length:
                    nextSmallestAdj = adjSet
                    smallestTile = tile
                    nextSmallestAdjTile = t

        if nextSmallestAdj is None:
            # logbook.info(f'no adjacent to smallest {smallest.name}:{smallest.length} to join to. Adding it directly to final sets.')
            finalSets.append(smallest)
        else:
            # logbook.info(f'Merging smallest {smallest.name}:{smallest.length} to nearby smallest {nextSmallestAdj.name}:{nextSmallestAdj.length}')
            _update_set_if_wrong_and_check_already_in_curset(globalVisited, smallestTile, nextSmallestAdjTile)

        completedSets.remove(smallest)

    finalSets.extend(completedSets)

    timeSpentJoiningResultingSets = time.perf_counter() - start
    start = time.perf_counter()

    reMergedSets = []
    for setHolder in finalSets:
        if setHolder.joined_to:
            continue

        actualSet = {t for t in itertools.chain.from_iterable(setHolder.sets)}
        reMergedSets.append(NamedSet(actualSet, setHolder.name))
    finalConvertTime = time.perf_counter() - start

    logbook.info(f'bifurcated {len(setToBifurcate)} tiles into {len(reMergedSets)} sets of rough size {breakThreshold} in {time.perf_counter() - fullStart:.5f} (iterations:{iter}, fullIterTime:{fullIterTime:.5f}, timeSpentJoiningResultingSets:{timeSpentJoiningResultingSets:.5f}, timeInUpdateIfWrongCheck:{timeInUpdateIfWrongCheck:.5f}, finalConvertTime:{finalConvertTime:.5f}, buildingNoOptionsTime:{buildingNoOptionsTime:.5f})')

    return reMergedSets


def _get_tiles_with_no_other_options(bifurcationMatrix: MapMatrixSet, setToBifurcate: typing.Set[Tile], breakThreshold: int) -> typing.Set[Tile]:
    halfBreak = breakThreshold // 2
    noOptionsMatrix: MapMatrix[typing.Tuple[int, int]] = MapMatrix(bifurcationMatrix.map)
    noOptionsStarter = {}
    i = 1
    for t in setToBifurcate:
        if SearchUtils.count(t.movable, lambda m: m in bifurcationMatrix) <= 1:
            noOptionsMatrix[t] = i, 1
            noOptionsStarter[t] = (i, 0, None)
            i += 1

    groups = [1] * (i + 1)
    groupJoined: typing.List[int | None] = [None] * (i + 1)

    def joinGroups(groupA: int, groupB: int):
        groupJoined[groupB] = groupA
        groups[groupA] += groups[groupB]
        groups[groupB] = 0

    def foreachFunc(tile: Tile, state):
        if tile not in bifurcationMatrix:
            return None

        i, curCount, fromTile = state

        for t in tile.movable:
            if t == fromTile:
                continue
            tupleOrNone = noOptionsMatrix[t]
            if tupleOrNone:
                tGroup, tCount = tupleOrNone
                # ran into another no options run
                pass


        # and SearchUtils.count(tile.movable, lambda m: m != fromTile and m in bifurcationMatrix) <= 1:



    SearchUtils.breadth_first_foreach_with_state(bifurcationMatrix.map, noOptionsStarter, maxDepth=1000, foreachFunc=foreachFunc)
