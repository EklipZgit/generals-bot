import inspect
import os
import pathlib
import time
import typing
import unittest

import EarlyExpandUtils
import SearchUtils
from ExpandUtils import get_optimal_expansion
from Path import Path
from Sim.TextMapLoader import TextMapLoader
from Tests.TestBase import TestBase
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase


class ExpansionUtils_get_optimal_expansion_tests(TestBase):

    def test__first_25_reroute__2_moves__should_find_2_tile_move(self):
        map, general = self.load_map_and_general(f'ExpandUtilsTestMaps/did_not_find_2_move_cap__turn34', turn=34)

        weightMap = self.get_opposite_general_distance_map(map, general)

        negTiles = set()
        negTiles.add(general)

        path = self.run_expansion(map, general, turns=2, enemyDistanceMap=weightMap, negativeTiles=negTiles)
        # should go 5,9 -> 5,10 -> 4,10
        self.assertIsNotNone(path)
        self.assertEquals(path.length, 2)
        self.assertEquals(path.start.tile, map.GetTile(5, 9))
        self.assertEquals(path.start.next.tile, map.GetTile(5, 10))
        self.assertEquals(path.start.next.next.tile, map.GetTile(4, 10))

    def run_expansion(
            self,
            map: MapBase,
            general: Tile,
            turns: int,
            enemyDistanceMap: typing.List[typing.List[int]],
            negativeTiles: typing.Set[Tile]
    ) -> typing.Union[Path, None]:
        targetPlayer = next(filter(lambda p: p.index != general.player, map.players))

        genDistances = self.get_from_general_weight_map(map, general)
        path = get_optimal_expansion(
            map,
            general.player,
            targetPlayer,
            turns,
            enemyDistanceMap,
            genDistances,
            territoryMap=self.get_empty_weight_map(map, empty_value=-1),
            innerChokes=self.get_empty_weight_map(map, empty_value=False),
            pathChokes=set(),
            negativeTiles=negativeTiles,
            leafMoves=[]
        )
        return path
