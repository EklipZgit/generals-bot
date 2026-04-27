from __future__ import annotations

import itertools
import random
import time
import typing
from collections import deque
from enum import Enum

import logbook

import Algorithms
import DebugHelper
import SearchUtils
from Algorithms import FastDisjointSet
from ArmyAnalyzer import ArmyAnalyzer
from BoardAnalyzer import BoardAnalyzer
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix, MapMatrixSet
from base.client.map import MapBase, Tile, TeamStats


class TileIsland(object):
    def __init__(self, tiles: typing.Iterable[Tile], team: int, tileCount: int | None = None, armySum: int | None = None, overrideUniqueId: int | None = None):
        if isinstance(tiles, set):
            self.tile_set: typing.Set[Tile] = tiles
        else:
            self.tile_set: typing.Set[Tile] = set(tiles)

        self.team: int = team

        self.tile_count: int = tileCount
        if self.tile_count is None:
            self.tile_count = len(self.tile_set)

        self.sum_army: int = armySum
        """
        Total army on this island. Does not pre-subtract the 1's that need to be left behind on the tiles.
        """
        if self.sum_army is None:
            self.sum_army = 0
            for t in self.tile_set:
                self.sum_army += t.army

        self.border_islands: typing.Set[TileIsland] = set()
        """
        Tile islands that border this island. This does not include parent islands - only leaf child islands are counted as borders.
        """
        #
        # self.border_tiles: typing.Set[Tile] = set()
        # """
        # Tiles that border this island
        # """
        #
        # self.outer_border_tiles: typing.Set[Tile] = set()
        # """
        # Tiles that border this island
        # """

        self.tile_count_all_adjacent_friendly: int = self.tile_count
        self.sum_army_all_adjacent_friendly: int = self.sum_army

        # adds about 1/10th of a millisecond to a tile island build
        self.tiles_by_army: typing.List[Tile] = [t for t in sorted(tiles, key=lambda tile: tile.army, reverse=True)]
        """Sorted from largest army to smallest army"""

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

        self.unique_id: int = overrideUniqueId
        if self.unique_id is None:
            self.unique_id = IslandNamer.get_int()

    def __str__(self) -> str:
        sampleTile = None
        if self.tile_set:
            sampleTile = str(next(iter(self.tile_set)))
        else:
            pass
        return f'{{t{self.team} {self.unique_id}/{self.name}: {self.tile_count}t {self.sum_army}a ({sampleTile})}}'

    def __repr__(self) -> str:
        return str(self)

    def __lt__(self, other: TileIsland | None):
        # if other is None:
        #     return False
        return self.sum_army < other.sum_army

    def __gt__(self, other: TileIsland | None):
        # if other is None:
        #     return True
        return self.sum_army > other.sum_army

    def __hash__(self) -> int:
        return self.unique_id

    def __eq__(self, other: TileIsland):
        if other is None:
            return False
        return self.unique_id == other.unique_id

    def clone(self, copyId: bool = False) -> TileIsland:
        # TODO this does not yet handle safely cloning all the bordered / full_island parent connections; they will be the originals still.
        overrideId = None
        if copyId:
            overrideId = self.unique_id
        copy = TileIsland([], -2, 0, 0, overrideUniqueId=overrideId)
        copy.tile_set = self.tile_set
        copy.team = self.team
        copy.tile_count = self.tile_count
        copy.sum_army = self.sum_army
        copy.border_islands = self.border_islands
        copy.tile_count_all_adjacent_friendly = self.tile_count_all_adjacent_friendly
        copy.sum_army_all_adjacent_friendly = self.sum_army_all_adjacent_friendly
        copy.tiles_by_army = self.tiles_by_army
        copy.cities = self.cities
        copy.child_islands = self.child_islands
        copy.full_island = self.full_island

        if copyId:
            copy.name = self.name
        elif self.name:
            copy.name = IslandNamer.get_letter()

        return copy

    def shortIdent(self) -> str:
        return f'({self.unique_id} {next(iter(self.tile_set))})'


class IslandNamer(object):
    letterStart: int = ord('A')
    letterEnd: int = ord('z')
    curLetter: int = 0
    letters: typing.List[str] = [chr(i) for i in range(letterStart, letterEnd + 1) if i not in [ord('['), ord('\\'), ord(']'), ord('^'), ord('_'), ord('`')]]
    numLetters = len(letters)

    curInt: int = 0

    @staticmethod
    def get_letter() -> str:
        letter = IslandNamer.letters[IslandNamer.curLetter]

        IslandNamer.curLetter += 1
        if IslandNamer.curLetter >= IslandNamer.numLetters:
            IslandNamer.curLetter = 0

        return letter

    @staticmethod
    def get_int() -> int:
        IslandNamer.curInt += 1

        return IslandNamer.curInt

    @staticmethod
    def reset():
        IslandNamer.curLetter = 0
        IslandNamer.curInt = 1


class IslandBuildMode(Enum):
    GroupByArmy = 1,
    BuildByDistance = 2,


class TileIslandBuilder(object):
    def __init__(self, map: MapBase, intergeneralAnalysis: ArmyAnalyzer, averageTileIslandSize: int | None = None):
        if averageTileIslandSize is None:
            averageTileIslandSize = 3
        self.map: MapBase = map
        self.teams: typing.List[int] = MapBase.get_teams_array(map)
        self.friendly_team: int = self.teams[map.player_index]
        # self.expandability_tiles_matrix: MapMatrixInterface[int] = MapMatrix(map, 0)
        # self.expandability_army_matrix: MapMatrixInterface[int] = MapMatrix(map, 0)
        self.desired_tile_island_size: int = averageTileIslandSize
        self.intergeneral_analysis: ArmyAnalyzer = intergeneralAnalysis

        # TODO examine networkX.algorithms.minors.blockmodel (aka quotient_graph with relabel=True and create_using=nx.MultiGraph()

        " -------------------------- ANYTHING YOU ADD TO THIS SECTION NEEDS TO BE COVERED IN reset_for_rebuild ---------------"
        self.tile_island_lookup: MapMatrixInterface[TileIsland] = MapMatrix(self.map, None)
        self.all_tile_islands: typing.Set[TileIsland] = set()
        """Does not include unreachable islands"""
        self.tile_islands_by_player: typing.List[typing.List[TileIsland]] = [[] for _ in self.map.players]
        self.tile_islands_by_player.append([])  # for -1 player
        self.tile_islands_by_team_id: typing.List[typing.List[TileIsland]] = [[] for _ in range(max(self.teams) + 2)]
        self.tile_islands_by_unique_id: typing.Dict[int, TileIsland] = {}
        self.large_tile_islands_by_team_id: typing.List[typing.Set[TileIsland]] = [set() for _ in range(max(self.teams) + 2)]
        self.large_tile_island_distances_by_team_id: typing.List[MapMatrixInterface[int] | None] = [MapMatrix(map, 1000) for _ in range(max(self.teams) + 2)]
        self.borders_by_island: typing.Dict[int, typing.Dict[int, typing.Set[Tile]]] = {}
        self._team_stats_by_player: typing.List[TeamStats] = []
        self._team_stats_by_team_id: typing.List[TeamStats] = []
        self.reset_for_rebuild()
        " -------------------------- ANYTHING YOU ADD TO THIS SECTION NEEDS TO BE COVERED IN reset_for_rebuild ---------------"

        self.break_apart_neutral_islands: bool = True
        # TODO ideally we should be able to turn this off and efficiently convert border gathers to their crossover options. See the gather to neutral middle in test_should_recognize_gather_into_top_path_is_best as an example of something that mis-calculates non-single-tile-island-borders
        self.force_territory_borders_to_single_tile_islands: bool = True
        """If True, any tile that borders a different teams territory will be a single-tile-island. Useful for algorithms that dont safely deal with skews along borders between islands."""

        self.log_debug: bool = DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE
        self.use_debug_asserts: bool = DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE

    def reset_for_rebuild(self):
        self.tile_island_lookup = MapMatrix(self.map, None)
        self.all_tile_islands = set()
        self.tile_islands_by_player = [[] for _ in self.map.players]
        self.tile_islands_by_player.append([])  # for -1 player
        self.tile_islands_by_team_id = [[] for _ in range(max(self.teams) + 2)]
        self.tile_islands_by_unique_id = {}
        self.large_tile_islands_by_team_id = [set() for _ in range(max(self.teams) + 2)]
        self.large_tile_island_distances_by_team_id = [MapMatrix(self.map, 1000) for _ in range(max(self.teams) + 2)]
        self._team_stats_by_player = []
        self._team_stats_by_team_id = []
        self.borders_by_island = {}

    def recalculate_tile_islands(self, enemyGeneralExpectedLocation: Tile | None, mode: IslandBuildMode = IslandBuildMode.GroupByArmy):
        start = time.perf_counter()
        self.reset_for_rebuild()

        logbook.info(f'building initial islands')
        self._team_stats_by_team_id = self.map.get_team_stats_lookup_by_team_id()  # yeah, shut up
        self._team_stats_by_player = [self._team_stats_by_team_id[p.team] for p in self.map.players]
        self._team_stats_by_player.append(self._team_stats_by_team_id[-1])

        newIslands = []
        gen = self.map.generals[self.map.player_index]

        tiles = [t for t in self.map.reachable_tiles]  # get_all_tiles()
        distMat = self.map.distance_mapper.get_tile_dist_matrix(gen)
        if mode == IslandBuildMode.BuildByDistance:
            tiles = sorted(tiles, key=lambda t: (t.player, distMat.raw[t.tile_index], t.tile_index))
        elif mode == IslandBuildMode.GroupByArmy:
            tiles = sorted(tiles, key=lambda t: (t.player, t.army, distMat.raw[t.tile_index], t.tile_index))

        for tile in tiles:
            if tile.isObstacle:
                continue
            # if tile not in self.map.reachableTiles:
            #     continue

            if self.tile_island_lookup.raw[tile.tile_index] is not None:
                continue

            newIsland = self._build_island_from_tile(tile, tile.player)
            brokenUp = self._break_up_initial_island_if_necessary(newIsland, mode)
            newIslands.extend(brokenUp)

        logbook.info(f'breaking apart large islands ({time.perf_counter() - start:.5f}s in)')

        self.all_tile_islands.clear()

        ourTeam = self.map.get_team_stats(self.map.player_index).teamId
        for island in newIslands:
            nextNewIslands = None
            if mode == IslandBuildMode.GroupByArmy and island.team == ourTeam:
                # we only break our own friendly islands up by player
                nextNewIslands = self._break_apart_island_by_army(island, primaryPlayer=self.map.player_index)
            elif mode == IslandBuildMode.GroupByArmy and island.team == -1:
                if self.break_apart_neutral_islands:
                    nextNewIslands = self._break_apart_island_if_too_large(island)
                else:
                    nextNewIslands = [island]
            elif mode == IslandBuildMode.BuildByDistance:
                nextNewIslands = self._break_apart_island_if_too_large(island)
            else:
                nextNewIslands = self._break_apart_island_if_too_large(island)

            for newIsland in nextNewIslands:
                self.all_tile_islands.add(newIsland)
                for teammate in self._team_stats_by_team_id[island.team].teamPlayers:
                    self.tile_islands_by_player[teammate].append(newIsland)
                self.tile_islands_by_team_id[newIsland.team].append(newIsland)

        logbook.info(f'building island borders ({time.perf_counter() - start:.5f}s in)')
        for island in self.all_tile_islands:
            # if not island.bordered:
            self._build_island_borders(island)
            self.tile_islands_by_unique_id[island.unique_id] = island

        logbook.info(f'building large island distances and sets ({time.perf_counter() - start:.5f}s in)')
        for team in self.teams:
            self._build_large_island_distances_for_team(team)

        nullIslandNonObstTiles = [
            t for t in self.map.tiles_by_index
            if not t.isObstacle and self.tile_island_lookup.raw[t.tile_index] is None
        ]
        if nullIslandNonObstTiles:
            logbook.info(
                f'recalculate_tile_islands POST-BUILD: {len(nullIslandNonObstTiles)} non-obstacle tile(s) with None island: '
                + ' | '.join(
                    f'{t} pl={t.player} army={t.army} isCity={t.isCity} isGen={t.isGeneral} '
                    f'isCostlyNeut={t.isCostlyNeutral} disc={t.discovered} isReachable={t in self.map.reachable_tiles} idx={t.tile_index}'
                    for t in nullIslandNonObstTiles
                )
            )
        else:
            logbook.info('recalculate_tile_islands POST-BUILD: all non-obstacle tiles have islands (no None)')

        if self.log_debug or self.use_debug_asserts:
            self.debug_verify_all_islands(context='recalculate_tile_islands')

        complete = time.perf_counter() - start
        logbook.info(f'islands all built in {complete:.5f}s')

    def update_tile_islands(self, enemyGeneralExpectedLocation: Tile | None, mode: IslandBuildMode = IslandBuildMode.GroupByArmy):
        logbook.info(f'update_tile_islands starting (turn={self.map.turn})')
        start = time.perf_counter()

        self._team_stats_by_team_id = self.map.get_team_stats_lookup_by_team_id()
        self._team_stats_by_player = [self._team_stats_by_team_id[p.team] for p in self.map.players]
        self._team_stats_by_player.append(self._team_stats_by_team_id[-1])

        changedTiles: typing.List[Tile] = []
        changedArmyTiles: typing.Set[Tile] = set()
        changedOwnerTiles: typing.Set[Tile] = set()
        impactedLeafIslands: typing.Set[TileIsland] = set()
        noIslandChangedTiles: typing.Set[Tile] = set()
        affectedTeams: typing.Set[int] = set()
        # Tiles whose army delta is fully handled by an intra/inter-island army move update
        # (no teardown required — just sum_army already patched in-place).
        armyMoveHandledTiles: typing.Set[Tile] = set()
        # Islands whose army changed but whose shape is unchanged (updated in-place).
        # They need a border refresh but no teardown.
        armyOnlyRefreshIslands: typing.Set[TileIsland] = set()

        for tile in self.map.tiles_by_index:
            ownerChanged = tile.delta.oldOwner != tile.player
            armyChanged = tile.delta.oldArmy != tile.army
            if not ownerChanged and not armyChanged:
                # Fast path: delta says nothing changed. But the lookup island may be stale
                # if the tile was silently reverted by fog-of-war (e.g. fill_out_tiles on
                # one turn sets player=0, fog resets it to -1 the next turn without a delta).
                existingIsland = self.tile_island_lookup.raw[tile.tile_index]
                if existingIsland is not None:
                    existingTeam = existingIsland.team if existingIsland.full_island is None else existingIsland.full_island.team
                    if existingTeam != self.teams[tile.player]:
                        ownerChanged = True
                    else:
                        continue
                else:
                    continue

            existingIsland = self.tile_island_lookup.raw[tile.tile_index]
            if existingIsland is not None:
                existingTeam = existingIsland.team if existingIsland.full_island is None else existingIsland.full_island.team
                if existingTeam != -1 and not ownerChanged and tile not in armyMoveHandledTiles:
                    # Army-only change on an owned tile. Check if this is a pure army move
                    # (army shifted between tiles of the same player) that needs no teardown.
                    pairedTile: Tile | None = tile.delta.fromTile if tile.delta.fromTile is not None else tile.delta.toTile
                    if pairedTile is not None and pairedTile.player == tile.player:
                        pairedIsland = self.tile_island_lookup.raw[pairedTile.tile_index]
                        if pairedIsland is not None:
                            if pairedIsland is existingIsland:
                                # Intra-island move: army moved within the same island.
                                # sum_army and tile topology are unchanged — nothing to rebuild.
                                armyMoveHandledTiles.add(tile)
                                armyMoveHandledTiles.add(pairedTile)
                                newArmy = sum(t.army for t in existingIsland.tile_set)
                                if self.use_debug_asserts and newArmy != sum(t.army for t in existingIsland.tile_set):
                                    logbook.warning(f'INTRA sum_army update tile={tile} paired={pairedTile} island={existingIsland} old={existingIsland.sum_army} new={newArmy} tiles={[(str(t), t.army) for t in existingIsland.tile_set]}')
                                existingIsland.sum_army = newArmy
                                existingIsland.tiles_by_army = sorted(existingIsland.tile_set, key=lambda t: t.army, reverse=True)
                                existingIsland.sum_army_all_adjacent_friendly = max(existingIsland.sum_army_all_adjacent_friendly, existingIsland.sum_army)
                                continue
                            elif pairedIsland.team == existingIsland.team:
                                # Inter-island move: army moved between two islands of the same team.
                                # Tile topology is unchanged; only sum_army needs updating on both islands.
                                armyMoveHandledTiles.add(tile)
                                armyMoveHandledTiles.add(pairedTile)
                                newExistArmy = sum(t.army for t in existingIsland.tile_set)
                                newPairedArmy = sum(t.army for t in pairedIsland.tile_set)
                                if self.use_debug_asserts:
                                    logbook.info(f'INTER sum_army update tile={tile} paired={pairedTile} existIsland={existingIsland} old={existingIsland.sum_army} new={newExistArmy} | pairedIsland={pairedIsland} old={pairedIsland.sum_army} new={newPairedArmy}')
                                existingIsland.sum_army = newExistArmy
                                existingIsland.tiles_by_army = sorted(existingIsland.tile_set, key=lambda t: t.army, reverse=True)
                                existingIsland.sum_army_all_adjacent_friendly = max(existingIsland.sum_army_all_adjacent_friendly, existingIsland.sum_army)
                                pairedIsland.sum_army = newPairedArmy
                                pairedIsland.tiles_by_army = sorted(pairedIsland.tile_set, key=lambda t: t.army, reverse=True)
                                pairedIsland.sum_army_all_adjacent_friendly = max(pairedIsland.sum_army_all_adjacent_friendly, pairedIsland.sum_army)
                                continue

            if tile in armyMoveHandledTiles:
                continue

            changedTiles.append(tile)
            if ownerChanged:
                changedOwnerTiles.add(tile)
                affectedTeams.add(self.teams[tile.delta.oldOwner])
            if armyChanged:
                changedArmyTiles.add(tile)
            affectedTeams.add(self.teams[tile.player])

            if existingIsland is not None:
                existingTeam = existingIsland.team if existingIsland.full_island is None else existingIsland.full_island.team
                if existingTeam == -1:
                    # Neutral island: only add the direct leaf containing this tile.
                    # _get_leaf_islands_for_island would return ALL siblings under the same full_island,
                    # tearing down the entire neutral blob and rebuilding it as one giant island.
                    # Neutral siblings are contiguous and unchanged — they never need to be rebuilt here.
                    directLeaf = existingIsland.full_island if existingIsland.full_island is not None else existingIsland
                    if directLeaf.child_islands is not None:
                        for child in directLeaf.child_islands:
                            if tile in child.tile_set:
                                impactedLeafIslands.add(child)
                                break
                    else:
                        impactedLeafIslands.add(existingIsland)
                elif ownerChanged:
                    # Ownership change: tile is leaving this island (and possibly joining another).
                    # The component topology may split or merge, so all siblings must be rebuilt.
                    # Exception: a solo-tile island has no shape to fix — it will simply be replaced
                    # by the new owner's island for this tile, so it needs teardown only of itself
                    # (not all siblings under the same full_island parent).
                    if existingIsland.tile_count == 1:
                        # Solo-tile island: only this island needs to be torn down; no siblings can be affected.
                        impactedLeafIslands.add(existingIsland)
                    else:
                        impactedLeafIslands.update(self._get_leaf_islands_for_island(existingIsland))
                else:
                    # Army-only change on an owned tile.
                    # Islands only need to be torn down and rebuilt if their SHAPE must change:
                    #   - Solo-tile islands: shape cannot change, update sum_army in-place.
                    #   - Enemy islands (any size): we never GroupByArmy-split enemy land, so shape
                    #     is unaffected by army changes; update sum_army in-place.
                    #   - Friendly multi-tile GroupByArmy island: the island is valid as long as every
                    #     tile in it has the same army value.  If the changed tile now has a different
                    #     army than its island-mates the island must be re-split; otherwise update in-place.
                    needsTeardown = False
                    if existingTeam == self.friendly_team and mode == IslandBuildMode.GroupByArmy:
                        # Check whether the new army value is still consistent with island-mates.
                        if existingIsland.tile_count > 1:
                            needsTeardown = any(t.army != tile.army for t in existingIsland.tile_set if t is not tile)
                        if not needsTeardown:
                            # Also check whether the tile now matches an adjacent tile in a DIFFERENT
                            # island — that would require a GroupByArmy merge (currently invalid state).
                            for adj in tile.movable:
                                if adj.isObstacle or adj.player != tile.player or adj.army != tile.army:
                                    continue
                                adjIsland = self.tile_island_lookup.raw[adj.tile_index]
                                if adjIsland is not None and adjIsland is not existingIsland:
                                    needsTeardown = True
                                    break
                    if needsTeardown:
                        impactedLeafIslands.update(self._get_leaf_islands_for_island(existingIsland))
                    else:
                        # Shape is unchanged — patch army stats in-place and record for border refresh.
                        newArmy = sum(t.army for t in existingIsland.tile_set)
                        if self.use_debug_asserts:
                            logbook.info(f'INPLACE sum_army update tile={tile} island={existingIsland} old={existingIsland.sum_army} new={newArmy}')
                        existingIsland.sum_army = newArmy
                        existingIsland.tiles_by_army = sorted(existingIsland.tile_set, key=lambda t: t.army, reverse=True)
                        existingIsland.sum_army_all_adjacent_friendly = existingIsland.sum_army
                        if existingIsland.full_island is not None:
                            fullIsland = existingIsland.full_island
                            newFullArmy = sum(child.sum_army for child in fullIsland.child_islands) if fullIsland.child_islands else existingIsland.sum_army
                            fullIsland.sum_army = newFullArmy
                            fullIsland.sum_army_all_adjacent_friendly = newFullArmy
                            for child in (fullIsland.child_islands or []):
                                child.sum_army_all_adjacent_friendly = newFullArmy
                        armyOnlyRefreshIslands.add(existingIsland)
            else:
                # Tile had no island (was outside reachable_tiles at recalculate time, e.g. undiscovered
                # pocket tile). It still needs to be rebuilt — track it separately so it is included in
                # impactedTiles even though there is no prior leaf island to tear down.
                noIslandChangedTiles.add(tile)

        logbook.info(
            f'update_tile_islands changedTiles ({len(changedTiles)}): '
            + ' | '.join(
                f'{t} pl={t.player}(was {t.delta.oldOwner}) army={t.army}(was {t.delta.oldArmy}) '
                f'isObst={t.isObstacle} isCostlyNeut={t.isCostlyNeutral} disc={t.discovered} idx={t.tile_index}'
                for t in changedTiles
            )
        )

        if len(changedTiles) == 0:
            complete = time.perf_counter() - start
            logbook.info(f'islands updated in {complete:.5f}s')
            return

        for tile in changedTiles:
            if tile in changedOwnerTiles:
                # Ownership change: any adjacent tile that is in a multi-tile island and that now
                # borders a different team must be extracted as a solo tile (force_territory_borders).
                if self.force_territory_borders_to_single_tile_islands:
                    for adj in tile.movable:
                        if adj.isObstacle or adj.player < 0:
                            continue
                        adjIsland = self.tile_island_lookup.raw[adj.tile_index]
                        if adjIsland is None or adjIsland.tile_count <= 1:
                            continue
                        adjTeam = adjIsland.team if adjIsland.full_island is None else adjIsland.full_island.team
                        if adjTeam == -1:
                            continue
                        # adj is in a multi-tile owned island. Re-check whether it must now be solo.
                        if self.must_tile_be_solo(adj, adjTeam):
                            impactedLeafIslands.update(self._get_leaf_islands_for_island(adjIsland))
                            affectedTeams.add(adjTeam)
                continue

            # Army-only changed tile that is being torn down (friendly GroupByArmy inconsistency).
            # Add any adjacent tile with the same army so it can be merged into the rebuilt component.
            tileIsland = self.tile_island_lookup.raw[tile.tile_index]
            if tileIsland not in impactedLeafIslands:
                continue
            mustBeSolo = tile.isCity or tile.isGeneral
            if mode != IslandBuildMode.GroupByArmy and self.force_territory_borders_to_single_tile_islands and not mustBeSolo:
                mustBeSolo = self.must_tile_be_solo(tile, self.teams[tile.player])
            if mustBeSolo:
                continue
            for adj in tile.movable:
                if adj.isObstacle:
                    continue
                if adj.player == tile.player and adj.army == tile.army:
                    adjIsland = self.tile_island_lookup.raw[adj.tile_index]
                    if adjIsland is not None:
                        impactedLeafIslands.update(self._get_leaf_islands_for_island(adjIsland))
                        affectedTeams.add(adjIsland.team)

        impactedTiles: typing.Set[Tile] = set()
        for island in impactedLeafIslands:
            impactedTiles.update(island.tile_set)
        impactedTiles.update(noIslandChangedTiles)

        if len(impactedTiles) == 0:
            complete = time.perf_counter() - start
            logbook.info(f'islands updated in {complete:.5f}s')
            return

        priorLeafIslandByTile: typing.Dict[Tile, TileIsland] = {}
        for island in impactedLeafIslands:
            for tile in island.tile_set:
                priorLeafIslandByTile[tile] = island

        logbook.info(
            f'update_tile_islands impactedLeafIslands ({len(impactedLeafIslands)}): '
            + ' | '.join(str(isl) for isl in impactedLeafIslands)
        )
        logbook.info(
            f'update_tile_islands impactedTiles ({len(impactedTiles)}): '
            + ' | '.join(str(t) for t in sorted(impactedTiles, key=lambda t: t.tile_index))
        )

        islandsBeforeUpdate: typing.Set[TileIsland] = set(self.all_tile_islands) if (self.log_debug or self.use_debug_asserts) else None

        # Snapshot full_island parents before clearing child pointers so they remain
        # available as reuse candidates in _rebuild_leaf_islands_from_component.
        priorParentsByLeaf: typing.Dict[int, TileIsland] = {}
        for island in impactedLeafIslands:
            if island.full_island is not None:
                priorParentsByLeaf[island.unique_id] = island.full_island

        # Remove impacted islands from all neighbors' border_islands to prevent phantom borders
        for island in impactedLeafIslands:
            for neighbor in island.border_islands:
                neighbor.border_islands.discard(island)
            island.border_islands.clear()

        for island in impactedLeafIslands:
            self._remove_leaf_island(island)
            self.borders_by_island.pop(island.unique_id, None)

        # Any full_island parent that lost ALL its children should be removed now
        # so it cannot act as a stale zombie island in subsequent updates.
        parentsToRemove = [p for p in set(priorParentsByLeaf.values()) if p.child_islands is not None and len(p.child_islands) == 0]
        for parent in parentsToRemove:
            # Clean up parent from neighbors' border_islands before removing
            for neighbor in parent.border_islands:
                neighbor.border_islands.discard(parent)
            parent.border_islands.clear()
            self._remove_leaf_island(parent)
            self.borders_by_island.pop(parent.unique_id, None)

        visited: typing.Set[Tile] = set()
        rebuiltIslands: typing.List[TileIsland] = []
        for tile in impactedTiles:
            if tile in visited:
                continue
            if tile.isObstacle:
                visited.add(tile)
                self.tile_island_lookup.raw[tile.tile_index] = None
                continue

            team = self.teams[tile.player]
            componentTiles = self._collect_contiguous_tiles(
                tile,
                impactedTiles,
                visited,
                lambda cur, nxt: not nxt.isObstacle and self.teams[nxt.player] == team
            )
            componentPriorLeafIslands = {priorLeafIslandByTile[t] for t in componentTiles if t in priorLeafIslandByTile and priorLeafIslandByTile[t].team == team}
            componentPriorParents = {priorParentsByLeaf[leaf.unique_id] for leaf in componentPriorLeafIslands if leaf.unique_id in priorParentsByLeaf}
            rebuiltIslands.extend(self._rebuild_leaf_islands_from_component(componentTiles, team, changedArmyTiles, changedOwnerTiles, componentPriorLeafIslands, mode, componentPriorParents))

        # Build refreshTiles and refreshIslands AFTER the rebuild so tile_island_lookup reflects
        # the final island assignments (including any children from _break_apart_island_if_too_large).
        # Pre-populating before rebuild was wrong: neighbors of rebuilt tiles that weren't adjacent
        # to changedTiles would get stale border_islands.
        refreshTiles: typing.Set[Tile] = set()
        for tile in impactedTiles:
            refreshTiles.add(tile)
            for adj in tile.movable:
                if not adj.isObstacle:
                    refreshTiles.add(adj)
        for tile in changedTiles:
            refreshTiles.add(tile)
            for adj in tile.movable:
                if not adj.isObstacle:
                    refreshTiles.add(adj)
            # Also add cardinal neighbours directly from the grid to handle asymmetric movable lists.
            # tile.movable can be asymmetric when a neighbour was undiscovered (obstacle) at map init:
            # the obstacle tile is removed from this tile's movable but never re-added on discovery.
            # tile.adjacents is similarly unreliable (undiscovered tiles get adjacents=[self] early,
            # causing init_grid_movable to skip them).  Grid-coordinate lookup is always correct.
            x, y = tile.x, tile.y
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < self.map.cols and 0 <= ny < self.map.rows:
                    adj = self.map.grid[ny][nx]
                    if not adj.isObstacle:
                        refreshTiles.add(adj)

        refreshIslands: typing.Set[TileIsland] = set(rebuiltIslands)
        for tile in refreshTiles:
            island = self.tile_island_lookup.raw[tile.tile_index]
            if island is not None and island not in impactedLeafIslands and island.child_islands is None:
                refreshIslands.add(island)
        # Islands that were updated in-place (army-only, no shape change) also need border refresh
        # in case any of their neighbours were rebuilt this turn.
        refreshIslands.update(isl for isl in armyOnlyRefreshIslands if isl not in impactedLeafIslands and isl.child_islands is None)

        for island in refreshIslands:
            self.borders_by_island.pop(island.unique_id, None)

        for island in refreshIslands:
            self._build_island_borders(island)
            self.tile_islands_by_unique_id[island.unique_id] = island

        # Add back-references: for every refreshed island, tell its current neighbors it exists.
        # This is done as a separate pass after all refreshIslands have been rebuilt so that
        # order-dependent phantoms cannot occur (an island cleared its border_islands during
        # its own _build_island_borders before we added the back-ref).
        # Guard: only add the back-ref when real tile-pair adjacency is confirmed, to avoid
        # propagating phantom refs caused by stale tile_island_lookup entries.
        for island in refreshIslands:
            for neighbor in island.border_islands:
                confirmed = any(
                    movable in neighbor.tile_set
                    for tile in island.tile_set
                    for movable in tile.movable
                ) or any(
                    movable in island.tile_set
                    for tile in neighbor.tile_set
                    for movable in tile.movable
                )
                if confirmed:
                    neighbor.border_islands.add(island)

        for team in affectedTeams:
            if team >= 0:
                self._build_large_island_distances_for_team(team)

        nullIslandNonObstTiles = [
            t for t in self.map.tiles_by_index
            if not t.isObstacle and self.tile_island_lookup.raw[t.tile_index] is None
        ]
        if nullIslandNonObstTiles:
            logbook.info(
                f'update_tile_islands POST-UPDATE: {len(nullIslandNonObstTiles)} non-obstacle tile(s) with None island: '
                + ' | '.join(
                    f'{t} pl={t.player} army={t.army} isCity={t.isCity} isGen={t.isGeneral} '
                    f'isCostlyNeut={t.isCostlyNeutral} disc={t.discovered} idx={t.tile_index}'
                    for t in nullIslandNonObstTiles
                )
            )
        else:
            logbook.info('update_tile_islands POST-UPDATE: all non-obstacle tiles have islands (no None)')

        if self.log_debug or self.use_debug_asserts:
            droppedIslands = [isl for isl in islandsBeforeUpdate if isl not in self.all_tile_islands]
            newIslands = [isl for isl in self.all_tile_islands if isl not in islandsBeforeUpdate]
            borderAdjustedIslands = [isl for isl in refreshIslands if isl in islandsBeforeUpdate and isl not in impactedLeafIslands]
            logbook.info(
                f'update_tile_islands DEBUG REPORT:\n'
                f'  dropped ({len(droppedIslands)}): '
                + ' | '.join(str(isl) for isl in droppedIslands)
                + f'\n  net-new ({len(newIslands)}): '
                + ' | '.join(str(isl) for isl in newIslands)
                + f'\n  border-adjusted ({len(borderAdjustedIslands)}): '
                + ' | '.join(str(isl) for isl in borderAdjustedIslands)
            )
            self.debug_verify_all_islands(context='update_tile_islands', deletingIslandSet=impactedLeafIslands)

        complete = time.perf_counter() - start
        logbook.info(f'islands updated in {complete:.5f}s')

    def _get_leaf_islands_for_island(self, island: TileIsland) -> typing.List[TileIsland]:
        if island.full_island is not None:
            island = island.full_island
        if island.child_islands is not None:
            return island.child_islands.copy()
        return [island]

    def debug_verify_island(self, island: TileIsland, deletingIslandSet: typing.Set[TileIsland], sourceLabel: str) -> typing.List[str]:
        """
        Validates a single TileIsland for structural consistency. Does NOT mutate anything.
        Returns a (possibly empty) list of error strings describing every invariant violation found.
        """
        errors: typing.List[str] = []
        prefix = f'[{sourceLabel} id={island.unique_id}/{island.name}]'

        # --- deletingIslandSet membership ---
        # An island in deletingIslandSet that was reused/re-registered is fine; only flag it if
        # it is truly gone (not in all_tile_islands) but still referenced somewhere.
        if island in deletingIslandSet and island not in self.all_tile_islands:
            errors.append(f'{prefix} island is in deletingIslandSet and not in all_tile_islands (dead island still referenced)')

        # --- tile_set basic sanity ---
        if island.tile_set is None:
            errors.append(f'{prefix} tile_set is None')
            return errors  # nothing else is safe to check
        if len(island.tile_set) == 0:
            errors.append(f'{prefix} tile_set is empty')

        # --- tile_count ---
        actualCount = len(island.tile_set)
        if island.tile_count != actualCount:
            errors.append(f'{prefix} tile_count mismatch: reported={island.tile_count} actual={actualCount}')

        # --- sum_army ---
        actualArmy = sum(t.army for t in island.tile_set)
        if island.sum_army != actualArmy:
            errors.append(f'{prefix} sum_army mismatch: reported={island.sum_army} actual={actualArmy}')

        # --- tile_count_all_adjacent_friendly vs tile_count ---
        if island.tile_count_all_adjacent_friendly < island.tile_count:
            errors.append(
                f'{prefix} tile_count_all_adjacent_friendly={island.tile_count_all_adjacent_friendly} < tile_count={island.tile_count} (must be >=)'
            )

        # --- sum_army_all_adjacent_friendly vs sum_army ---
        if island.sum_army_all_adjacent_friendly < island.sum_army:
            errors.append(
                f'{prefix} sum_army_all_adjacent_friendly={island.sum_army_all_adjacent_friendly} < sum_army={island.sum_army} (must be >=)'
            )

        # --- tiles_by_army ---
        if island.tiles_by_army is None:
            errors.append(f'{prefix} tiles_by_army is None')
        else:
            tbaSet = set(island.tiles_by_army)
            if tbaSet != island.tile_set:
                missing = island.tile_set - tbaSet
                extra = tbaSet - island.tile_set
                if missing:
                    errors.append(f'{prefix} tiles_by_army missing {len(missing)} tile(s): {sorted(str(t) for t in missing)[:5]}')
                if extra:
                    errors.append(f'{prefix} tiles_by_army has {len(extra)} extra tile(s) not in tile_set: {sorted(str(t) for t in extra)[:5]}')
            if len(island.tiles_by_army) != len(set(island.tiles_by_army)):
                errors.append(f'{prefix} tiles_by_army contains duplicate tiles')
            # verify descending army order
            for i in range(len(island.tiles_by_army) - 1):
                if island.tiles_by_army[i].army < island.tiles_by_army[i + 1].army:
                    errors.append(
                        f'{prefix} tiles_by_army not sorted descending at index {i}: '
                        f'{island.tiles_by_army[i].army} < {island.tiles_by_army[i+1].army}'
                    )
                    break  # one report per island is enough

        # --- cities ---
        if island.cities is None:
            errors.append(f'{prefix} cities is None')
        else:
            actualCities = [t for t in island.tile_set if t.isCity]
            if set(island.cities) != set(actualCities):
                missing = set(actualCities) - set(island.cities)
                extra = set(island.cities) - set(actualCities)
                if missing:
                    errors.append(f'{prefix} cities missing {len(missing)} city tile(s): {sorted(str(t) for t in missing)[:5]}')
                if extra:
                    errors.append(f'{prefix} cities has {len(extra)} stale city tile(s) not in tile_set or not isCity: {sorted(str(t) for t in extra)[:5]}')

        # --- full_island / child_islands cross-references ---
        if island.full_island is not None:
            if island.full_island is island:
                errors.append(f'{prefix} full_island is self (self-cycle)')
            else:
                fi = island.full_island
                if fi.child_islands is None:
                    errors.append(f'{prefix} full_island {fi.unique_id}/{fi.name} has child_islands=None but this island claims it as parent')
                else:
                    if island not in fi.child_islands:
                        errors.append(f'{prefix} this island is not listed in full_island {fi.unique_id}/{fi.name}.child_islands')
                if fi.full_island is not None:
                    errors.append(f'{prefix} full_island {fi.unique_id}/{fi.name} itself has a full_island set (grandparent chain unsupported)')
                if fi.team != island.team:
                    errors.append(f'{prefix} full_island {fi.unique_id}/{fi.name} has team={fi.team} but this island.team={island.team}')
                if not island.tile_set.issubset(fi.tile_set):
                    diff = island.tile_set - fi.tile_set
                    errors.append(f'{prefix} tile_set is not a subset of full_island {fi.unique_id}/{fi.name}.tile_set; extra tiles: {sorted(str(t) for t in diff)[:5]}')

        if island.child_islands is not None:
            if len(island.child_islands) == 0:
                errors.append(f'{prefix} child_islands is set but empty (should be None if no children)')
            childTileUnion: typing.Set[Tile] = set()
            seenChildIds: typing.Set[int] = set()
            for child in island.child_islands:
                if child is island:
                    errors.append(f'{prefix} child_islands contains self')
                    continue
                if child.unique_id in seenChildIds:
                    errors.append(f'{prefix} child_islands contains duplicate id={child.unique_id}')
                seenChildIds.add(child.unique_id)
                if child.full_island is not island:
                    errors.append(
                        f'{prefix} child {child.unique_id}/{child.name}.full_island={child.full_island} '
                        f'does not point back to this island'
                    )
                if child.team != island.team:
                    errors.append(f'{prefix} child {child.unique_id}/{child.name} has team={child.team} != parent.team={island.team}')
                childTileUnion.update(child.tile_set)
            if childTileUnion != island.tile_set:
                missing = island.tile_set - childTileUnion
                extra = childTileUnion - island.tile_set
                if missing:
                    errors.append(f'{prefix} child tile union missing {len(missing)} tile(s) from parent tile_set: {sorted(str(t) for t in missing)[:5]}')
                if extra:
                    errors.append(f'{prefix} child tile union has {len(extra)} extra tile(s) not in parent tile_set: {sorted(str(t) for t in extra)[:5]}')

        # --- all tiles: team alignment and lookup pointer ---
        for tile in island.tile_set:
            actualTeam = self.teams[tile.player]
            if actualTeam != island.team:
                errors.append(
                    f'{prefix} tile {tile} has player={tile.player} (team={actualTeam}) but island.team={island.team}'
                )
            lookupIsland = self.tile_island_lookup.raw[tile.tile_index]
            if lookupIsland is not island:
                errors.append(
                    f'{prefix} tile {tile} tile_island_lookup points to {lookupIsland} (id={getattr(lookupIsland,"unique_id",None)}) not this island'
                )

        # --- border_islands: every border must be a leaf, tiles must align with lookup, back-ref must exist ---
        for border in island.border_islands:
            if border is island:
                errors.append(f'{prefix} border_islands contains self')
                continue
            if border in deletingIslandSet and border not in self.all_tile_islands:
                errors.append(f'{prefix} border {border.unique_id}/{border.name} is in deletingIslandSet and not in all_tile_islands (stale ref to dead island)')
            # borders must be leaf islands — a leaf has child_islands=None
            # (full_island being set is fine: it just means the leaf is a child of a broken-up parent)
            if border.child_islands is not None:
                errors.append(
                    f'{prefix} border {border.unique_id}/{border.name} has child_islands set '
                    f'— borders should only be leaf islands, not parent/full islands'
                )
            if island not in border.border_islands:
                errors.append(
                    f'{prefix} border {border.unique_id}/{border.name} does not have this island in its border_islands (missing back-ref)'
                )
            for btile in border.tile_set:
                lookupIsland = self.tile_island_lookup.raw[btile.tile_index]
                if lookupIsland is not border:
                    errors.append(
                        f'{prefix} border {border.unique_id}/{border.name}: tile {btile} lookup={lookupIsland} '
                        f'(id={getattr(lookupIsland,"unique_id",None)}) but expected the border island'
                    )
                actualTeam = self.teams[btile.player]
                if actualTeam != border.team:
                    errors.append(
                        f'{prefix} border {border.unique_id}/{border.name}: tile {btile} player={btile.player} '
                        f'(team={actualTeam}) but border.team={border.team}'
                    )

        # --- movable neighbours: every non-obstacle neighbour is either in this island or in border_islands ---
        # Use symmetric adjacency: if tile→movable confirms adjacency, we require border presence.
        # We do NOT require the reverse (movable→tile) because movable lists can be asymmetric
        # when a tile transitions from undiscovered (obstacle) to discovered.
        for tile in island.tile_set:
            for movable in tile.movable:
                if movable.isObstacle:
                    continue
                neighborIsland = self.tile_island_lookup.raw[movable.tile_index]
                if neighborIsland is None:
                    continue
                if neighborIsland is island:
                    if movable not in island.tile_set:
                        errors.append(
                            f'{prefix} tile {tile} neighbour {movable}: lookup maps to THIS island but movable is not in tile_set'
                        )
                else:
                    if neighborIsland not in island.border_islands:
                        errors.append(
                            f'{prefix} tile {tile} neighbour {movable}: lookup island {neighborIsland.unique_id}/{neighborIsland.name} '
                            f'is adjacent but not in border_islands'
                        )
                    # Only flag missing back-ref if the reverse adjacency also holds (symmetric movable).
                    # Asymmetric movable (tile discovery transition) can legitimately produce a one-way border.
                    reverseAdjacent = any(m is tile for m in movable.movable)
                    if reverseAdjacent and island not in neighborIsland.border_islands:
                        errors.append(
                            f'{prefix} tile {tile} neighbour {movable}: neighbour island {neighborIsland.unique_id}/{neighborIsland.name} '
                            f'does not have this island in its border_islands (missing back-ref)'
                        )

        # --- border_islands must all be truly adjacent (at least one tile pair confirms adjacency) ---
        # Check both directions: island→border AND border→island, because movable lists can be
        # asymmetric when a tile transitions from undiscovered (obstacle) to discovered.
        for border in island.border_islands:
            adjacencyConfirmed = any(
                movable in border.tile_set
                for tile in island.tile_set
                for movable in tile.movable
            ) or any(
                movable in island.tile_set
                for tile in border.tile_set
                for movable in tile.movable
            )
            if not adjacencyConfirmed:
                errors.append(
                    f'{prefix} border {border.unique_id}/{border.name} is listed in border_islands but no tile pair is actually adjacent (phantom border)'
                )

        return errors

    def debug_verify_all_islands(self, context: str = '', deletingIslandSet: typing.Set[TileIsland] | None = None):
        """
        Iterates every island reachable via all lookup tables and index structures, calls
        debug_verify_island on each, aggregates all errors, and raises AssertionError with
        the full report if any are found.  Only call when self.log_debug is True.
        """
        if deletingIslandSet is None:
            deletingIslandSet = set()
        allErrors: typing.List[str] = []
        seenIds: typing.Set[int] = set()

        # --- tile_island_lookup: primary source of truth ---
        for tile in self.map.tiles_by_index:
            if tile.isObstacle:
                continue
            island = self.tile_island_lookup.raw[tile.tile_index]
            if island is None:
                if tile in self.map.pathable_tiles:
                    allErrors.append(f'{context}: tile {tile} is pathable but not in tile_island_lookup')
                continue
            if island.unique_id in seenIds:
                continue
            seenIds.add(island.unique_id)
            allErrors.extend(self.debug_verify_island(island, deletingIslandSet, f'{context}:lookup@{tile}'))

        # --- all_tile_islands: flag zombies (present in set but no lookup tile points here) ---
        for island in self.all_tile_islands:
            if island.unique_id not in seenIds:
                seenIds.add(island.unique_id)
                allErrors.extend(self.debug_verify_island(island, deletingIslandSet, f'{context}:all_tile_islands(zombie)'))
                sampleTile = next(iter(island.tile_set), None)
                allErrors.append(
                    f'[{context}:all_tile_islands id={island.unique_id}/{island.name}] '
                    f'ZOMBIE: in all_tile_islands but no lookup tile points to it (sample={sampleTile})'
                )

        # --- tile_islands_by_unique_id: must be a bijection with all_tile_islands ---
        for uid, island in self.tile_islands_by_unique_id.items():
            if uid != island.unique_id:
                allErrors.append(
                    f'[{context}:by_unique_id key={uid}] key mismatch: island.unique_id={island.unique_id}'
                )
            if island not in self.all_tile_islands:
                allErrors.append(
                    f'[{context}:by_unique_id id={uid}] present in by_unique_id but NOT in all_tile_islands: {island}'
                )
        for island in self.all_tile_islands:
            if island.unique_id not in self.tile_islands_by_unique_id:
                allErrors.append(
                    f'[{context}:all_tile_islands id={island.unique_id}] in all_tile_islands but missing from tile_islands_by_unique_id: {island}'
                )
            elif self.tile_islands_by_unique_id[island.unique_id] is not island:
                allErrors.append(
                    f'[{context}:all_tile_islands id={island.unique_id}] tile_islands_by_unique_id[{island.unique_id}] '
                    f'is a different object than the island in all_tile_islands'
                )

        # --- tile_islands_by_team_id: every island in all_tile_islands must appear exactly once ---
        for island in self.all_tile_islands:
            team = island.team
            if team < 0:
                teamList = self.tile_islands_by_team_id[-1] if -1 < len(self.tile_islands_by_team_id) else []
            else:
                teamList = self.tile_islands_by_team_id[team] if team < len(self.tile_islands_by_team_id) else []
            count = teamList.count(island)
            if count == 0:
                allErrors.append(
                    f'[{context}:by_team_id team={team}] island {island.unique_id}/{island.name} '
                    f'in all_tile_islands but not in tile_islands_by_team_id[{team}]'
                )
            elif count > 1:
                allErrors.append(
                    f'[{context}:by_team_id team={team}] island {island.unique_id}/{island.name} '
                    f'appears {count}x in tile_islands_by_team_id[{team}] (should be exactly once)'
                )

        # --- tile_islands_by_player: every island must appear for each teammate ---
        for island in self.all_tile_islands:
            team = island.team
            if team < 0:
                continue  # neutral islands are not in by_player
            stats = self._team_stats_by_team_id[team] if team < len(self._team_stats_by_team_id) else None
            if stats is None:
                continue
            for teammate in stats.teamPlayers:
                playerList = self.tile_islands_by_player[teammate] if teammate < len(self.tile_islands_by_player) else []
                count = playerList.count(island)
                if count == 0:
                    allErrors.append(
                        f'[{context}:by_player player={teammate}] island {island.unique_id}/{island.name} '
                        f'(team={team}) in all_tile_islands but not in tile_islands_by_player[{teammate}]'
                    )
                elif count > 1:
                    allErrors.append(
                        f'[{context}:by_player player={teammate}] island {island.unique_id}/{island.name} '
                        f'appears {count}x in tile_islands_by_player[{teammate}] (should be exactly once)'
                    )

        # --- borders_by_island: keys must correspond to live islands ---
        for uid in self.borders_by_island:
            if uid not in self.tile_islands_by_unique_id:
                allErrors.append(
                    f'[{context}:borders_by_island uid={uid}] key present but island not in tile_islands_by_unique_id (stale entry)'
                )

        if allErrors:
            raise AssertionError(
                f'debug_verify_all_islands ({context}) found {len(allErrors)} error(s):\n'
                + '\n'.join(allErrors)
            )
        logbook.info(f'debug_verify_all_islands ({context}) passed with no problems found.')

    def _remove_leaf_island(self, island: TileIsland):
        self.all_tile_islands.discard(island)

        teamIslands = self.tile_islands_by_team_id[island.team]

        if island in teamIslands:
            teamIslands.remove(island)

        stats = self._team_stats_by_team_id[island.team]
        for teammate in stats.teamPlayers:
            playerIslands = self.tile_islands_by_player[teammate]
            if island in playerIslands:
                playerIslands.remove(island)

        self.tile_islands_by_unique_id.pop(island.unique_id, None)
        island.border_islands.clear()
        for tile in island.tile_set:
            self.tile_island_lookup.raw[tile.tile_index] = None

        # Clear parent ↔ child linkage so stale pointers can't cause cross-team corruption.
        if island.full_island is not None:
            parent = island.full_island
            if parent.child_islands is not None:
                try:
                    parent.child_islands.remove(island)
                except ValueError:
                    pass
            parent.tile_set -= island.tile_set
            parent.tile_count = len(parent.tile_set)
            island.full_island = None
        if island.child_islands is not None:
            for child in island.child_islands:
                if child.full_island is island:
                    child.full_island = None
            island.child_islands = None

    def _register_leaf_island(self, island: TileIsland):
        if island.name is None or island.name == '':
            raise AssertionError(f'leaf_island {island.unique_id} has no name')
        self.all_tile_islands.add(island)
        self.tile_islands_by_team_id[island.team].append(island)
        stats = self._team_stats_by_team_id[island.team]
        for teammate in stats.teamPlayers:
            self.tile_islands_by_player[teammate].append(island)
        self.tile_islands_by_unique_id[island.unique_id] = island
        for tile in island.tile_set:
            self.tile_island_lookup.raw[tile.tile_index] = island

    def _update_island_state(self, island: TileIsland, tiles: typing.Iterable[Tile], team: int, tileCount: int | None = None, armySum: int | None = None) -> TileIsland:
        tileSet = tiles if isinstance(tiles, set) else set(tiles)
        if tileCount is None:
            tileCount = len(tileSet)
        if armySum is None:
            armySum = sum(tile.army for tile in tileSet)

        island.tile_set = tileSet
        island.team = team
        island.tile_count = tileCount
        island.sum_army = armySum
        # Do NOT clear border_islands here — _build_island_borders will be called for this
        # island as part of refreshIslands and will pre-remove stale back-refs using the OLD
        # border_islands before rebuilding them from the new tile_set.  Clearing here would
        # destroy the old neighbor list that _build_island_borders needs for pre-removal.
        island.tile_count_all_adjacent_friendly = tileCount
        island.sum_army_all_adjacent_friendly = armySum
        island.tiles_by_army = [t for t in sorted(tileSet, key=lambda tile: tile.army, reverse=True)]
        island.cities = [t for t in island.tiles_by_army if t.isCity]
        island.child_islands = None
        island.full_island = None

        return island

    def _link_leaf_islands_to_full_island(self, fullIsland: TileIsland, leafIslands: typing.List[TileIsland], aggregateTileCount: int, aggregateArmy: int):
        normalizedLeafIslands = [island for island in leafIslands if island is not fullIsland]
        fullIsland.child_islands = normalizedLeafIslands.copy()
        fullIsland.full_island = None

        for island in normalizedLeafIslands:
            island.full_island = fullIsland
            island.tile_count_all_adjacent_friendly = aggregateTileCount
            island.sum_army_all_adjacent_friendly = aggregateArmy
            self._register_leaf_island(island)

        if len(normalizedLeafIslands) != len(leafIslands):
            fullIsland.tile_count_all_adjacent_friendly = aggregateTileCount
            fullIsland.sum_army_all_adjacent_friendly = aggregateArmy
            # Do NOT call _register_leaf_island(fullIsland) here.
            # Full_island parents are aggregate containers — their tile_set is the union of all
            # leaf children and registering it would stomp the correct child lookup entries with
            # the parent, causing stale tile_island_lookup entries for tiles that get reassigned
            # to a different team's island in subsequent turns.
            if fullIsland.name is None or fullIsland.name == '':
                raise AssertionError(f'full_island {fullIsland.unique_id} has no name')

    def _take_best_matching_prior_island(self, candidateTiles: typing.Set[Tile], priorIslands: typing.Set[TileIsland]) -> TileIsland | None:
        bestIsland: TileIsland | None = None
        bestOverlap = 0
        for island in priorIslands:
            overlap = len(candidateTiles.intersection(island.tile_set))
            if overlap > bestOverlap:
                bestOverlap = overlap
                bestIsland = island

        if bestIsland is not None:
            priorIslands.remove(bestIsland)

        return bestIsland

    def _collect_contiguous_tiles(self, startTile: Tile, allowedTiles: typing.Set[Tile], visited: typing.Set[Tile], canTraverse: typing.Callable[[Tile, Tile], bool]) -> typing.Set[Tile]:
        found: typing.Set[Tile] = set()
        queue = deque([startTile])
        while queue:
            cur = queue.popleft()

            if cur in visited or cur not in allowedTiles:
                continue

            visited.add(cur)
            found.add(cur)
            for nxt in cur.movable:
                if nxt in visited or nxt not in allowedTiles:
                    continue
                if canTraverse(cur, nxt):
                    queue.append(nxt)

        return found

    def _rebuild_leaf_islands_from_component(self, componentTiles: typing.Set[Tile], team: int, changedArmyTiles: typing.Set[Tile], changedOwnerTiles: typing.Set[Tile], priorLeafIslands: typing.Set[TileIsland], mode: IslandBuildMode, priorFullIslands: typing.Set[TileIsland] | None = None) -> typing.List[TileIsland]:
        if len(componentTiles) == 0:
            return []

        aggregateTileCount = len(componentTiles)
        aggregateArmy = sum(tile.army for tile in componentTiles)
        priorLeafIslands = set(priorLeafIslands)
        if priorFullIslands is None:
            priorFullIslands = {island.full_island for island in priorLeafIslands if island.full_island is not None and island.full_island is not island}
        else:
            priorFullIslands = set(priorFullIslands)

        forcedSoloTiles: typing.Set[Tile] = set()
        pendingArmyTiles: typing.Set[Tile] = set()
        shouldForceBorderSolo = mode != IslandBuildMode.GroupByArmy
        for tile in componentTiles:
            mustBeSolo = tile.isCity or tile.isGeneral
            if shouldForceBorderSolo and self.force_territory_borders_to_single_tile_islands and not mustBeSolo:
                mustBeSolo = self.must_tile_be_solo(tile, team)

            if tile in changedOwnerTiles:
                forcedSoloTiles.add(tile)
                continue
            if mustBeSolo:
                forcedSoloTiles.add(tile)
                continue
            if tile in changedArmyTiles:
                pendingArmyTiles.add(tile)
                continue

        baseTiles = componentTiles.difference(forcedSoloTiles).difference(pendingArmyTiles)
        leafIslands: typing.List[TileIsland] = []
        leafIslandByTile: typing.Dict[Tile, TileIsland] = {}
        groupByArmyWithinComponent = mode == IslandBuildMode.GroupByArmy and team == self.friendly_team

        for tile in forcedSoloTiles:
            candidateTiles = {tile}
            island = self._take_best_matching_prior_island(candidateTiles, priorLeafIslands)
            if island is None:
                island = TileIsland(candidateTiles, team, 1, tile.army)
                island.name = '!' + IslandNamer.get_letter()
            else:
                self._update_island_state(island, candidateTiles, team, 1, tile.army)
            island.full_island = None
            island.child_islands = None
            leafIslands.append(island)
            leafIslandByTile[tile] = island

        visited: typing.Set[Tile] = set()
        for tile in baseTiles:
            if tile in visited:
                continue
            tileSet = self._collect_contiguous_tiles(
                tile,
                baseTiles,
                visited,
                lambda cur, nxt: self.teams[nxt.player] == team and (not groupByArmyWithinComponent or nxt.army == cur.army)
            )
            island = self._take_best_matching_prior_island(tileSet, priorLeafIslands)
            if island is None:
                island = TileIsland(tileSet, team, len(tileSet), sum(t.army for t in tileSet))
                island.name = '%' + IslandNamer.get_letter()
            else:
                self._update_island_state(island, tileSet, team, len(tileSet), sum(t.army for t in tileSet))
            brokenUp = self._break_apart_island_if_too_large(island, priorLeafIslands)
            if len(brokenUp) == 1 and brokenUp[0] is island:
                # Not split — clear any stale full_island/child_islands from a prior recalculate
                island.full_island = None
                island.child_islands = None
            leafIslands.extend(brokenUp)
            for brokenIsland in brokenUp:
                for islandTile in brokenIsland.tile_set:
                    leafIslandByTile[islandTile] = brokenIsland

        for tile in pendingArmyTiles:
            matchingIslands: typing.List[TileIsland] = []
            seenIslands: typing.Set[int] = set()
            for adj in tile.movable:
                if adj.player != tile.player or adj.army != tile.army:
                    continue
                adjIsland = leafIslandByTile.get(adj)
                if adjIsland is None or adjIsland.tile_count >= 4 or adjIsland.unique_id in seenIslands:
                    continue
                seenIslands.add(adjIsland.unique_id)
                matchingIslands.append(adjIsland)

            if len(matchingIslands) == 0:
                candidateTiles = {tile}
                island = self._take_best_matching_prior_island(candidateTiles, priorLeafIslands)
                if island is None:
                    island = TileIsland(candidateTiles, team, 1, tile.army)
                    island.name = '*' + IslandNamer.get_letter()
                else:
                    self._update_island_state(island, candidateTiles, team, 1, tile.army)
                leafIslands.append(island)
                leafIslandByTile[tile] = island
                continue

            targetIsland = matchingIslands[0]
            targetIsland.tile_set.add(tile)
            leafIslandByTile[tile] = targetIsland
            for extraIsland in matchingIslands[1:]:
                if extraIsland is targetIsland:
                    continue
                targetIsland.tile_set.update(extraIsland.tile_set)
                leafIslands.remove(extraIsland)
                for mergedTile in extraIsland.tile_set:
                    leafIslandByTile[mergedTile] = targetIsland

            targetIsland.tile_count = len(targetIsland.tile_set)
            targetIsland.sum_army = sum(t.army for t in targetIsland.tile_set)
            targetIsland.tiles_by_army = [t for t in sorted(targetIsland.tile_set, key=lambda islandTile: islandTile.army, reverse=True)]
            targetIsland.cities = [t for t in targetIsland.tiles_by_army if t.isCity]

        if len(leafIslands) == 1 and leafIslands[0].tile_count == aggregateTileCount:
            island = leafIslands[0]
            island.full_island = None
            island.child_islands = None
            island.tile_count_all_adjacent_friendly = aggregateTileCount
            island.sum_army_all_adjacent_friendly = aggregateArmy
            self._register_leaf_island(island)
            return [island]

        priorFullIslands.difference_update(leafIslands)
        fullIsland = self._take_best_matching_prior_island(componentTiles, priorFullIslands)
        if fullIsland is None:
            fullIsland = TileIsland(componentTiles, team, aggregateTileCount, aggregateArmy)
            fullIsland.name = '&' + IslandNamer.get_letter()
        else:
            self._update_island_state(fullIsland, componentTiles, team, aggregateTileCount, aggregateArmy)
        self._link_leaf_islands_to_full_island(fullIsland, leafIslands, aggregateTileCount, aggregateArmy)

        return leafIslands

    def _build_island_from_tile(self, startTile: Tile, player: int) -> TileIsland:
        teamId = self.teams[player]
        teammates = self.map.get_teammates(player)

        tilesInIsland = []

        if startTile.isCity or startTile.isGeneral:
            tilesInIsland.append(startTile)

        # if self.force_territory_borders_to_single_tile_islands:
        #     if len(teammates) > 1:
        #         def foreachFunc(tile: Tile) -> bool:
        #             if tile.player in teammates:
        #                 mustBeSolo = tile.isCity or tile.isGeneral or self.must_tile_be_solo(tile, teamId)
        #                 if mustBeSolo:
        #                     return True
        #                 tilesInIsland.append(tile)
        #                 return False
        #             return True
        #     else:
        #         def foreachFunc(tile: Tile) -> bool:
        #             if tile.player == player:
        #                 mustBeSolo = tile.isCity or tile.isGeneral or self.must_tile_be_solo(tile, teamId)
        #                 if mustBeSolo:
        #                     return True
        #                 tilesInIsland.append(tile)
        #                 return False
        #             return True
        # else:
        if len(teammates) > 1:
            def foreachFunc(tile: Tile) -> bool:
                if tile.isCity or tile.isGeneral:
                    return True
                if tile.player in teammates:
                    tilesInIsland.append(tile)
                    return False
                return True
        else:
            def foreachFunc(tile: Tile) -> bool:
                if tile.isCity or tile.isGeneral:
                    return True
                if tile.player == player:
                    tilesInIsland.append(tile)
                    return False
                return True

        SearchUtils.breadth_first_foreach_fast_no_neut_cities(
            self.map,
            [startTile],
            maxDepth=1000,
            foreachFunc=foreachFunc
        )

        island = TileIsland(tilesInIsland, teamId, tileCount=len(tilesInIsland))
        island.name = '_' + IslandNamer.get_letter()

        for tile in tilesInIsland:
            self.tile_island_lookup.raw[tile.tile_index] = island

        return island

    def _build_island_borders(self, island: TileIsland):
        # Remove this island from all its current neighbors' border_islands first
        # to prevent stale back-references when island shape changes
        for neighbor in island.border_islands:
            neighbor.border_islands.discard(island)
        island.border_islands.clear()  # in case its already populated. TODO eventually optimize this away if this is at all slow.
        # island.border_tiles = set()
        for tile in island.tile_set:
            for movable in tile.movable:
                if movable.isObstacle:
                    continue

                adjIsland = self.tile_island_lookup.raw[movable.tile_index]
                if adjIsland is island:
                    continue

                # island.border_tiles.add(movable)
                if adjIsland is not None:
                    island.border_islands.add(adjIsland)

    def _break_apart_island_if_too_large(self, island: TileIsland, priorLeafIslands: typing.Set[TileIsland] | None = None) -> typing.List[TileIsland]:
        # stats = self._team_stats_by_team_id[island.team]
        tile_island_split_cutoff: int = int(self.desired_tile_island_size * 1.5)
        if island.tile_count > tile_island_split_cutoff and (island.team != -1 or self.break_apart_neutral_islands):

            # Ok, break the island up.
            breakIntoSubCount = round(island.tile_count / self.desired_tile_island_size)
            if breakIntoSubCount <= 1:
                return [island]

            brokenInto = []

            largestEnemyBorder: TileIsland | None = None
            self._build_island_borders(island)
            # find largest enemy border
            for border in sorted(island.border_islands, key=lambda borderIsland: (borderIsland.team, borderIsland.tile_count, min((t.x, t.y) for t in borderIsland.tile_set))):
                if border.team == island.team or border.team == -1:
                    continue

                if border.full_island:
                    border = border.full_island

                if largestEnemyBorder is None or (largestEnemyBorder.tile_count, min((t.x, t.y) for t in largestEnemyBorder.tile_set)) < (border.tile_count, min((t.x, t.y) for t in border.tile_set)):
                    largestEnemyBorder = border

            if largestEnemyBorder is None and island.border_islands:
                largestEnemyBorder = min(island.border_islands, key=lambda borderIsland: (borderIsland.team, borderIsland.tile_count, min((t.x, t.y) for t in borderIsland.tile_set)))
            if largestEnemyBorder is None:
                largestEnemyBorder = island

            # Walk to the root parent so full_island is never more than one level deep.
            rootIsland = island.full_island if island.full_island is not None else island

            sets = bifurcate_set_into_n_contiguous(self.map, largestEnemyBorder.tile_set, island.tile_set, breakIntoSubCount, self.log_debug)
            for namedTileSet in sets:
                tileSet = namedTileSet.set
                if priorLeafIslands is not None:
                    priorIsland = self._take_best_matching_prior_island(tileSet, priorLeafIslands)
                else:
                    priorIsland = None
                if priorIsland is not None:
                    self._update_island_state(priorIsland, tileSet, island.team, len(tileSet), sum(t.army for t in tileSet))
                    newIsland = priorIsland
                    newIsland.name = namedTileSet.name
                else:
                    newIsland = TileIsland(tileSet, island.team)
                    newIsland.name = namedTileSet.name
                newIsland.full_island = rootIsland
                newIsland.sum_army_all_adjacent_friendly = island.sum_army_all_adjacent_friendly
                newIsland.tile_count_all_adjacent_friendly = island.tile_count_all_adjacent_friendly

                brokenInto.append(newIsland)
                for tile in tileSet:
                    self.tile_island_lookup.raw[tile.tile_index] = newIsland

            # Replace `island` in the root's child list with the new sub-pieces, if island was already a child.
            if island.full_island is not None and rootIsland.child_islands is not None:
                rootChildren = rootIsland.child_islands
                if island in rootChildren:
                    insertIdx = rootChildren.index(island)
                    rootChildren[insertIdx:insertIdx + 1] = brokenInto
                else:
                    rootChildren.extend(brokenInto)

            island.child_islands = brokenInto.copy()

            return brokenInto
        else:
            return [island]

    def _break_up_initial_island_if_necessary(self, island: TileIsland, mode: IslandBuildMode) -> typing.List[TileIsland]:
        # Clear stale parent/child pointers from any prior recalculate run on this reused island object.
        island.full_island = None
        island.child_islands = None
        brokenUp = []
        leftoverTiles = island.tile_set.copy()
        # shouldForceBorderSolo = mode != IslandBuildMode.GroupByArmy
        shouldForceBorderSolo = True
        for tile in island.tile_set:
            mustBeSolo = tile.isCity or tile.isGeneral
            if shouldForceBorderSolo and self.force_territory_borders_to_single_tile_islands and not mustBeSolo:
                mustBeSolo = self.must_tile_be_solo(tile, island.team)

            if mustBeSolo:
                leftoverTiles.discard(tile)
                tilesInIsland = [tile]

                newIsland = TileIsland(tilesInIsland, island.team)
                newIsland.full_island = island
                newIsland.sum_army_all_adjacent_friendly = island.sum_army_all_adjacent_friendly
                newIsland.tile_count_all_adjacent_friendly = island.tile_count_all_adjacent_friendly
                newIsland.name = f'!{IslandNamer.get_letter()}'

                brokenUp.append(newIsland)
                for t in tilesInIsland:
                    self.tile_island_lookup.raw[t.tile_index] = newIsland

        if len(brokenUp) == 0:
            return [island]

        if len(leftoverTiles) > 0:
            forest = Algorithms.FastDisjointSet(t.tile_index for t in leftoverTiles)
            for t in leftoverTiles:
                for mv in t.movable:
                    if mv in leftoverTiles:
                        forest.merge(t.tile_index, mv.tile_index)

            subsets = forest.subsets()
            for subset in subsets:
                newIsland = TileIsland([self.map.tiles_by_index[i] for i in subset], island.team, len(subset))
                newIsland.full_island = island
                newIsland.sum_army_all_adjacent_friendly = island.sum_army_all_adjacent_friendly
                newIsland.tile_count_all_adjacent_friendly = island.tile_count_all_adjacent_friendly
                newIsland.name = f'+{IslandNamer.get_letter()}'

                if self.log_debug:
                    logbook.info(f'new broken island {newIsland}')

                brokenUp.append(newIsland)
                for i in subset:
                    self.tile_island_lookup.raw[i] = newIsland

        island.child_islands = brokenUp.copy()
        return brokenUp

    def _break_apart_island_by_army(self, island: TileIsland, primaryPlayer: int) -> typing.List[TileIsland]:
        if island.team != -1:
            visited: typing.Set[Tile] = set()
            contiguousArmyGroups: typing.List[typing.Set[Tile]] = []
            for tile in sorted(island.tile_set, key=lambda islandTile: (islandTile.army, islandTile.x, islandTile.y)):
                if tile in visited:
                    continue

                tileSet = self._collect_contiguous_tiles(
                    tile,
                    island.tile_set,
                    visited,
                    lambda cur, nxt: nxt.army == cur.army
                )
                contiguousArmyGroups.append(tileSet)

            if len(contiguousArmyGroups) <= 1:
                return [island]

            # Walk to the root parent so full_island is never more than one level deep.
            rootIsland = island.full_island if island.full_island is not None else island

            brokenByBorders = []

            for tileSet in contiguousArmyGroups:
                newIsland = TileIsland(tileSet, island.team)
                newIsland.full_island = rootIsland
                newIsland.sum_army_all_adjacent_friendly = island.sum_army_all_adjacent_friendly
                newIsland.tile_count_all_adjacent_friendly = island.tile_count_all_adjacent_friendly
                newIsland.name = IslandNamer.get_letter()

                brokenByBorders.append(newIsland)
                for tile in tileSet:
                    self.tile_island_lookup.raw[tile.tile_index] = newIsland

            # Replace `island` in the root's child list with the new sub-pieces, if island was already a child.
            if island.full_island is not None and rootIsland.child_islands is not None:
                rootChildren = rootIsland.child_islands
                if island in rootChildren:
                    insertIdx = rootChildren.index(island)
                    rootChildren[insertIdx:insertIdx + 1] = brokenByBorders
                else:
                    rootChildren.extend(brokenByBorders)

            island.child_islands = brokenByBorders.copy()

            return brokenByBorders
        else:
            return [island]

    def _build_large_island_distances_for_team(self, team: int):
        targetTeam = self.map.team_ids_by_player_index[team]

        tileMinimum = min(12, max(1, self.map.players[self.map.player_index].tileCount // 3))

        largeIslands = []

        islandsByTeam = self.tile_islands_by_team_id[team]

        if len(islandsByTeam) == 0:
            logbook.info(f'NO TILE ISLANDS FOR LARGE ISLANDS (targetTeam {targetTeam})')
            self.large_tile_island_distances_by_team_id[team] = None
            self.large_tile_islands_by_team_id[team] = set()
            return

        for pIndx in self.map.get_team_stats_by_team_id(team).livingPlayers:
            if pIndx >= 0:
                playerObj = self.map.players[pIndx]
                if len(playerObj.tiles) > 0:
                    tileMinimum = max(tileMinimum, playerObj.tileCount // 4)

            largeIslands = [i for i in islandsByTeam if i.tile_count_all_adjacent_friendly > tileMinimum]
            if len(largeIslands) == 0:
                tileMinimum = tileMinimum // 2
                largeIslands = [i for i in islandsByTeam if i.tile_count_all_adjacent_friendly > tileMinimum]

        if len(largeIslands) == 0:
            largeIslands = [i for i in islandsByTeam if i.tile_count_all_adjacent_friendly > 7]
        if len(largeIslands) == 0:
            largeIslands = islandsByTeam

        islandTiles = [t for t in itertools.chain.from_iterable(i.tiles_by_army for i in largeIslands)]

        largeIslandSet = {i for i in largeIslands}
        distanceToLargeIslandsMap = SearchUtils.build_distance_map_matrix_with_skip(self.map, islandTiles)

        self.large_tile_island_distances_by_team_id[team] = distanceToLargeIslandsMap
        self.large_tile_islands_by_team_id[team] = largeIslandSet

        if self.log_debug:
            logbook.info(f'LARGE TILE ISLANDS (targetTeam {targetTeam}) ARE {", ".join([str(i) for i in largeIslands])}')

    def get_inner_border_tiles(self, islandWhoseBorderTilesToReturn: TileIsland, islandTilesMustBorder: TileIsland | None = None, skipFriendlyBorders: bool = True) -> typing.Set[Tile]:
        """
        Returns the border tiles of a tile island.
        If islandTilesMustBorder is None (the default) then returns all tiles in the island that border an un-friendly island.
        Safe to modify the output of this. The output is always a copy of original sets.

        @param islandWhoseBorderTilesToReturn:
        @param islandTilesMustBorder:
        @param skipFriendlyBorders: if True (default) then when islandTilesMustBorder is not provided, this will not return tiles that only border friendly islands. If false, all borders will be returned. Ignored if islandTilesMustBorder is provided.
        @return:
        """

        borderLookup: typing.Dict[int, typing.Set[Tile]] = self.get_island_border_tile_lookup(islandWhoseBorderTilesToReturn)

        borderTiles: typing.Set[Tile] = set()
        if islandTilesMustBorder is not None:
            borderTiles.update(borderLookup[islandTilesMustBorder.unique_id])
        else:
            for borderIslandId, borderSet in borderLookup.items():
                bi = self.tile_islands_by_unique_id[borderIslandId]
                if skipFriendlyBorders and bi.team == islandWhoseBorderTilesToReturn.team:
                    continue
                borderTiles.update(borderSet)

        return borderTiles

    def get_island_border_tile_lookup(self, islandTilesMustBorder: TileIsland) -> typing.Dict[int, typing.Set[Tile]]:
        """Gets a dict {borderIslandId: {setOfTilesInside_This_IslandThatBorder_borderIslandId}}"""
        borderLookup = self.borders_by_island.get(islandTilesMustBorder.unique_id, None)
        if borderLookup is None:
            borderLookup = {}
            for tile in islandTilesMustBorder.tile_set:
                for mv in tile.movable:
                    borderIsland = self.tile_island_lookup.raw[mv.tile_index]
                    if borderIsland is None:
                        continue
                    if borderIsland == islandTilesMustBorder:
                        continue
                    borderSet: typing.Set[Tile] = borderLookup.get(borderIsland.unique_id, None)
                    if not borderSet:
                        borderSet = {tile}
                        borderLookup[borderIsland.unique_id] = borderSet
                    else:
                        borderSet.add(tile)
            self.borders_by_island[islandTilesMustBorder.unique_id] = borderLookup

        return borderLookup

    def add_tile_islands_to_view_info(self, viewInfo, printIslandInfoLines: bool = False, renderIslandNames: bool = True):
        if renderIslandNames:
            viewInfo.add_info_line('ISLAND NAME PREFIXES:')
            viewInfo.add_info_line('!  forced solo during breakup')
            viewInfo.add_info_line('+  remaining after solo\'d')
            viewInfo.add_info_line('*  rebuild pending army tiles')
            viewInfo.add_info_line('%  rebuild contiguous to base tile')
        for island in sorted(self.all_tile_islands, key=lambda i: (i.team, i.unique_id)):
            _rng = random.Random(hash(island.unique_id))
            color = (_rng.randint(0, 255), _rng.randint(0, 255), _rng.randint(0, 255))
            zoneAlph = 80
            divAlph = 200
            if island.team == -1:
                zoneAlph //= 2
                divAlph //= 2

            viewInfo.add_map_zone(island.tile_set, color, alpha=zoneAlph)
            viewInfo.add_map_division(island.tile_set, color, alpha=divAlph)

            if island.name and renderIslandNames:
                for tile in island.tile_set:
                    if viewInfo.bottomRightGridText.raw[tile.tile_index]:
                        viewInfo.midRightGridText.raw[tile.tile_index] = island.name
                    else:
                        viewInfo.bottomRightGridText.raw[tile.tile_index] = island.name
                    viewInfo.topRightGridText.raw[tile.tile_index] = island.unique_id


            if printIslandInfoLines:
                viewInfo.add_info_line(f'{island.team}: island {island.unique_id}/{island.name} - {island.sum_army}a/{island.tile_count}t ({island.sum_army_all_adjacent_friendly}a/{island.tile_count_all_adjacent_friendly}t) {str(island.tile_set)}')

    # just us impl
    # def must_tile_be_solo(self, tile: Tile, teamId: int) -> bool:
    #     mustBeSolo = False
    #     bordersUs = teamId == self.friendly_team
    #     for adj in tile.movable:
    #         adjTeam = self.teams[adj.player]
    #         if adjTeam != teamId:
    #             mustBeSolo = True
    #             if not bordersUs and adjTeam == self.friendly_team:
    #                 bordersUs = True
    #             if bordersUs:
    #                 break
    #
    #     return mustBeSolo and bordersUs

    # all borders impl
    def must_tile_be_solo(self, tile: Tile, teamId: int) -> bool:
        for adj in tile.movable:
            if self.teams[adj.player] != teamId:
                return True

        if teamId != self.friendly_team:
            # walls (missing adjacents) + obstacle neighbors count as blocked sides
            blockedSides = (4 - len(tile.movable)) + sum(1 for adj in tile.movable if adj.isObstacle)
            if blockedSides >= 3:
                return True

        return False

class SetHolder(object):
    def __init__(self):
        self.sets: typing.List[typing.Set] = [set()]
        self.length: int = 0
        self.complete: bool = False
        self.name = IslandNamer.get_letter()
        self.joined_to: SetHolder | None = None
        self.sample_tile: Tile | None = None

    def join_with(self, other: SetHolder):
        """Other set must be disjoint from this set."""
        self.length += other.length
        self.sets.extend(other.sets)
        other.joined_to = self
        if other.sample_tile is not None and (self.sample_tile is None or _tile_sort_key(other.sample_tile) < _tile_sort_key(self.sample_tile)):
            self.sample_tile = other.sample_tile

    def add(self, item):
        """DOES NOT CHECK FOR DUPLICATES, A DUPLICATE COULD BE IN ANOTHER ENTRY"""
        self.sets[0].add(item)
        self.length += 1
        if self.sample_tile is None or _tile_sort_key(item) < _tile_sort_key(self.sample_tile):
            self.sample_tile = item

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
    if fromSet is curSet or not fromSet or not curSet or fromSet.complete or curSet.complete:
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


def _update_set_if_wrong_and_check_already_in_curset_and_army_matches(globalVisited, current: Tile, fromTile: Tile) -> bool:
    fromSet = globalVisited[fromTile]
    curSet = globalVisited[current]
    alreadyVisited = curSet is not None
    if fromTile.army != current.army or not fromSet or fromSet is curSet or not curSet or fromSet.complete or curSet.complete:
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


def _tile_sort_key(tile: Tile) -> typing.Tuple[int, int]:
    return tile.x, tile.y


def _island_stable_sort_key(island: TileIsland) -> typing.Tuple[int, int, int, int, int]:
    sampleTile = min(island.tile_set, key=_tile_sort_key)
    return island.team, island.tile_count, island.sum_army, sampleTile.x, sampleTile.y


def _set_holder_stable_sort_key(setHolder: SetHolder) -> typing.Tuple[int, int, int]:
    if setHolder.sample_tile is None:
        return setHolder.length, -1, -1
    sampleTile = setHolder.sample_tile
    return setHolder.length, sampleTile.x, sampleTile.y


def bifurcate_set_into_n_contiguous(
        map: MapBase,
        startPoints: typing.Set[Tile],
        setToBifurcate: typing.Concatenate[typing.Container[Tile], typing.Iterable[Tile]],
        numBreaks: int,
        logDebug: bool = False
) -> typing.List[NamedSet]:
    if len(setToBifurcate) <= numBreaks:
        return [NamedSet({t}, IslandNamer.get_letter()) for t in sorted(setToBifurcate, key=_tile_sort_key)]

    fullStart = time.perf_counter()

    # Aim to over-break up the tile set so we can recombine back together
    rawBreakThresh = len(setToBifurcate) / numBreaks / 2 - 1
    breakThreshold = max(1, int(rawBreakThresh))

    bifurcationMatrix = MapMatrixSet(map, setToBifurcate)
    buildingNoOptionsTime = 0.0
    fullIterTime = 0.0
    timeInUpdateIfWrongCheck = 0.0

    buildingNoOptionsTime += time.perf_counter() - fullStart
    start = time.perf_counter()

    maxDepth = 1000

    visitedSetLookup: MapMatrixInterface[SetHolder | None] = MapMatrix(map, None)

    frontier = deque()
    allSets = set()
    for tile in sorted(startPoints, key=_tile_sort_key):
        anyInc = False
        for movable in sorted(tile.movable, key=_tile_sort_key):

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
        if _update_set_if_wrong_and_check_already_in_curset(visitedSetLookup, current, fromTile):
            # timeInUpdateIfWrongCheck += time.perf_counter() - updateStart
            continue
        # timeInUpdateIfWrongCheck += time.perf_counter() - updateStart
        if dist > maxDepth:
            break

        # respectComplete = current not in tilesWithNoOtherOptions
        respectComplete = True
        # if not respectComplete:
        #     logbook.info(f'   tilesWithNoOtherOptions contained {current} ({fromTile}->{current}) (deque {len(frontier)})')

        fromIsland = None
        if fromIsland is None or (fromIsland.complete and respectComplete):
            fromIsland = SetHolder()
            # logbook.info(f'new island {fromIsland.name} at {current} ({fromTile}->{current}) (deque {len(frontier)})')
            allSets.add(fromIsland)

        # logbook.info(f'adding {current} to {fromIsland.name} ({fromTile}->{current}) (deque {len(frontier)})')
        fromIsland.add(current)

        visitedSetLookup[current] = fromIsland
        if current.isObstacle:
            continue

        if fromIsland.length >= breakThreshold:
            if not fromIsland.complete:
                fromIsland.complete = True
                # logbook.info(f'marking island {fromIsland.name} complete at length {fromIsland.length}/{breakThreshold}: {fromIsland.name} (deque {len(frontier)})')

        newDist = dist + 1
        for nextTile in sorted(current.movable, key=_tile_sort_key):  # new spots to try

            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            # TODO TODO TODO
            if nextTile is fromTile:
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
    for setHolder in sorted(allSets, key=_set_holder_stable_sort_key):

        if setHolder.joined_to or setHolder.length == 0:
            continue
        completedSets.append(setHolder)
        # these need to be marked back to incomplete or else we can't join them back up again.
        setHolder.complete = False

    if logDebug:
        if DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
            logbook.info(
            f'split {len(setToBifurcate)} tiles into {len(completedSets)} sets of rough size {breakThreshold} in {time.perf_counter() - fullStart:.5f}\r\nRECOMBINING SMALLEST:')

    # join small sets to larger

    finalSets = []
    while len(finalSets) + len(completedSets) > numBreaks and len(completedSets) > 0:
        smallest = min(completedSets, key=_set_holder_stable_sort_key)

        nextSmallestAdj = None
        smallestTile = None
        nextSmallestAdjTile = None
        for tile in sorted(itertools.chain.from_iterable(smallest.sets), key=_tile_sort_key):
            for t in sorted(tile.movable, key=_tile_sort_key):
                adjSet = visitedSetLookup[t]
                if adjSet is None or adjSet == smallest or adjSet == nextSmallestAdj or adjSet.length == 0:
                    continue

                if nextSmallestAdj is None or _set_holder_stable_sort_key(adjSet) < _set_holder_stable_sort_key(nextSmallestAdj) or (_set_holder_stable_sort_key(adjSet) == _set_holder_stable_sort_key(nextSmallestAdj) and _tile_sort_key(t) < _tile_sort_key(nextSmallestAdjTile)):
                    nextSmallestAdj = adjSet
                    smallestTile = tile
                    nextSmallestAdjTile = t

        if nextSmallestAdj is None:
            # logbook.info(f'no adjacent to smallest {smallest.name}:{smallest.length} to join to. Adding it directly to final sets.')
            finalSets.append(smallest)
        else:
            # logbook.info(f'Merging smallest {smallest.name}:{smallest.length} to nearby smallest {nextSmallestAdj.name}:{nextSmallestAdj.length}')
            _update_set_if_wrong_and_check_already_in_curset(visitedSetLookup, smallestTile, nextSmallestAdjTile)

        completedSets.remove(smallest)

    finalSets.extend(sorted(completedSets, key=_set_holder_stable_sort_key))

    timeSpentJoiningResultingSets = time.perf_counter() - start
    start = time.perf_counter()

    reMergedSets = []
    for setHolder in sorted(finalSets, key=_set_holder_stable_sort_key):

        if setHolder.joined_to:
            continue

        actualSet = {t for t in itertools.chain.from_iterable(setHolder.sets)}
        reMergedSets.append(NamedSet(actualSet, setHolder.name))
    finalConvertTime = time.perf_counter() - start

    if logDebug:
        if DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
            logbook.info(
            f'bifurcated {len(setToBifurcate)} tiles into {len(reMergedSets)} sets of rough size {breakThreshold} in {time.perf_counter() - fullStart:.5f} (iterations:{iter}, fullIterTime:{fullIterTime:.5f}, timeSpentJoiningResultingSets:{timeSpentJoiningResultingSets:.5f}, timeInUpdateIfWrongCheck:{timeInUpdateIfWrongCheck:.5f}, finalConvertTime:{finalConvertTime:.5f}, buildingNoOptionsTime:{buildingNoOptionsTime:.5f})')

    return reMergedSets


def bifurcate_set_into_n_contiguous_by_army(
        map: MapBase,
        startPoints: typing.Set[Tile],
        setToBifurcate: typing.Concatenate[typing.Container[Tile], typing.Iterable[Tile]],
        numBreaks: int = 1,
        doNotRecombine: bool = True
) -> typing.List[NamedSet]:
    """
    @param map:
    @param startPoints:
    @param setToBifurcate:
    @param numBreaks:
    @return:
    """
    if len(setToBifurcate) <= numBreaks:
        return [NamedSet({t}, IslandNamer.get_letter()) for t in sorted(setToBifurcate, key=_tile_sort_key)]

    fullStart = time.perf_counter()

    # Aim to over-break up the tile set so we can recombine back together
    if doNotRecombine:
        rawBreakThresh = len(setToBifurcate) / numBreaks
    else:
        rawBreakThresh = len(setToBifurcate) / numBreaks / 2 - 1
    breakThreshold = max(1, int(rawBreakThresh))

    bifurcationMatrix = MapMatrixSet(map, setToBifurcate)
    buildingNoOptionsTime = 0.0
    fullIterTime = 0.0
    timeInUpdateIfWrongCheck = 0.0

    buildingNoOptionsTime += time.perf_counter() - fullStart
    start = time.perf_counter()

    maxDepth = 1000

    visitedSetLookup: MapMatrixInterface[SetHolder | None] = MapMatrix(map, None)

    frontier = SearchUtils.HeapQueue()
    allSets = set()
    for tile in sorted(startPoints, key=_tile_sort_key):
        anyInc = False
        for movable in sorted(tile.movable, key=_tile_sort_key):
            if movable not in bifurcationMatrix:
                continue
            anyInc = True
            frontier.put((True, 0, movable, tile))
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
        (isSameArmy, dist, current, fromTile) = frontier.get()
        # updateStart = time.perf_counter()
        if _update_set_if_wrong_and_check_already_in_curset_and_army_matches(visitedSetLookup, current, fromTile):
            # timeInUpdateIfWrongCheck += time.perf_counter() - updateStart
            continue
        # timeInUpdateIfWrongCheck += time.perf_counter() - updateStart
        if dist > maxDepth:
            break

        # respectComplete = current not in tilesWithNoOtherOptions
        respectComplete = True
        # if not respectComplete:
        #     logbook.info(f'   tilesWithNoOtherOptions contained {current} ({fromTile}->{current}) (deque {len(frontier)})')

        fromIsland = None
        if isSameArmy:
            fromIsland = visitedSetLookup[fromTile]
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

        visitedSetLookup[current] = fromIsland
        if current.isObstacle:
            continue

        if fromIsland.length >= breakThreshold:
            if not fromIsland.complete:
                fromIsland.complete = True
                # logbook.info(f'marking island {fromIsland.name} complete at length {fromIsland.length}/{breakThreshold}: {fromIsland.name} (deque {len(frontier)})')

        newDist = dist + 1
        for nextTile in sorted(current.movable, key=_tile_sort_key):  # new spots to try
            if nextTile is fromTile:
                continue
            if nextTile in bifurcationMatrix:
                frontier.put((nextTile.army == current.army, newDist, nextTile, current))
            # if nextTile in tilesWithNoOtherOptions:
            #     frontier.append((nextTile, current, newDist))
            # elif nextTile in bifurcationMatrix:
            #     frontier.appendleft((nextTile, current, newDist))

    fullIterTime += time.perf_counter() - start
    start = time.perf_counter()

    completedSets = []
    for setHolder in sorted(allSets, key=_set_holder_stable_sort_key):
        if setHolder.joined_to or setHolder.length == 0:
            continue
        completedSets.append(setHolder)
        # these need to be marked back to incomplete or else we can't join them back up again.
        setHolder.complete = False

    if DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
        logbook.info(
        f'split {len(setToBifurcate)} tiles into {len(completedSets)} sets by army in {time.perf_counter() - fullStart:.5f}\r\nRECOMBINING SMALLEST:')

    # join small sets to larger
    if doNotRecombine:
        finalSets = completedSets
    else:
        finalSets = _recombine_sets_by_army(numBreaks, completedSets, visitedSetLookup)

    timeSpentJoiningResultingSets = time.perf_counter() - start
    start = time.perf_counter()

    reMergedSets = []
    for setHolder in sorted(finalSets, key=_set_holder_stable_sort_key):
        if setHolder.joined_to:
            continue

        actualSet = {t for t in itertools.chain.from_iterable(setHolder.sets)}
        reMergedSets.append(NamedSet(actualSet, setHolder.name))
    finalConvertTime = time.perf_counter() - start

    if DebugHelper.IS_DEBUG_OR_UNIT_TEST_MODE:
        logbook.info(
        f'bifurcated {len(setToBifurcate)} tiles by army into {len(reMergedSets)} sets of rough size {breakThreshold} in {time.perf_counter() - fullStart:.5f} (iterations:{iter}, fullIterTime:{fullIterTime:.5f}, timeSpentJoiningResultingSets:{timeSpentJoiningResultingSets:.5f}, timeInUpdateIfWrongCheck:{timeInUpdateIfWrongCheck:.5f}, finalConvertTime:{finalConvertTime:.5f}, buildingNoOptionsTime:{buildingNoOptionsTime:.5f})')

    return reMergedSets


def _recombine_sets_by_army(numBreaks: int, completedSets: typing.List[SetHolder], visitedSetLookup: MapMatrixInterface[SetHolder | None]) -> typing.List[SetHolder]:
    finalSets = []
    while len(finalSets) + len(completedSets) > numBreaks and len(completedSets) > 0:
        smallest = min(completedSets, key=_set_holder_stable_sort_key)

        nextSmallestAdj = None
        smallestTile = None
        nextSmallestAdjTile = None
        for tile in sorted(itertools.chain.from_iterable(smallest.sets), key=_tile_sort_key):
            for t in sorted(tile.movable, key=_tile_sort_key):
                adjSet = visitedSetLookup[t]
                if adjSet is None or adjSet == smallest or adjSet == nextSmallestAdj or adjSet.length == 0:
                    continue

                if nextSmallestAdj is None or _set_holder_stable_sort_key(adjSet) < _set_holder_stable_sort_key(nextSmallestAdj) or (_set_holder_stable_sort_key(adjSet) == _set_holder_stable_sort_key(nextSmallestAdj) and _tile_sort_key(t) < _tile_sort_key(nextSmallestAdjTile)):
                    nextSmallestAdj = adjSet
                    smallestTile = tile
                    nextSmallestAdjTile = t

        if nextSmallestAdj is None:
            # logbook.info(f'no adjacent to smallest {smallest.name}:{smallest.length} to join to. Adding it directly to final sets.')
            finalSets.append(smallest)
        else:
            # logbook.info(f'Merging smallest {smallest.name}:{smallest.length} to nearby smallest {nextSmallestAdj.name}:{nextSmallestAdj.length}')
            _update_set_if_wrong_and_check_already_in_curset(visitedSetLookup, smallestTile, nextSmallestAdjTile)

        completedSets.remove(smallest)

    finalSets.extend(sorted(completedSets, key=_set_holder_stable_sort_key))

    return finalSets


def _get_tiles_with_no_other_options(bifurcationMatrix: MapMatrixSet, setToBifurcate: typing.Set[Tile], breakThreshold: int) -> typing.Set[Tile]:
    halfBreak = breakThreshold // 2
    noOptionsMatrix: MapMatrixInterface[typing.Tuple[int, int]] = MapMatrix(bifurcationMatrix.map)
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
