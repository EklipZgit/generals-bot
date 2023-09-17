import typing
from ExpandUtils import get_optimal_expansion
from Path import Path
from Sim.GameSimulator import GameSimulatorHost
from Tests.TestBase import TestBase
from base.client.map import Tile, TILE_EMPTY, TILE_MOUNTAIN, MapBase

class ExpansionTests(TestBase):
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

    def test_should_not_split_for_neutral_while_exploring_enemy_path_with_largish_army(self):
        debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and False
        mapFile = 'GameContinuationEntries/should_not_split_for_neutral_while_exploring_enemy_path_with_largish_army___SxyrToG62---b--95.txtmap'
        # intentionally pretend it is turn 94 so we give it time for the last neutral capture
        map, general, enemyGeneral = self.load_map_and_generals(mapFile, 94)

        self.enable_search_time_limits_and_disable_debug_asserts()

        # # Grant the general the same fog vision they had at the turn the map was exported
        rawMap, _ = self.load_map_and_general(mapFile, 94)

        simHost = GameSimulatorHost(map, player_with_viewer=general.player, playerMapVision=rawMap, allAfkExceptMapPlayer=True)

        simHost.sim.set_tile_vision(general.player, 12, 1, hidden=True, undiscovered=False)
        simHost.sim.set_tile_vision(general.player, 13, 1, hidden=True, undiscovered=True)
        simHost.sim.set_tile_vision(general.player, 13, 2, hidden=True, undiscovered=True)
        simHost.sim.set_tile_vision(general.player, 13, 3, hidden=True, undiscovered=True)

        winner = simHost.run_sim(run_real_time=debugMode, turn_time=0.5, turns=6)
        self.assertIsNone(winner)
        #should have taken 5 enemy tiles and one neutral
        self.assertEqual(45, simHost.sim.players[general.player].map.players[general.player].tileCount)

        # this should be how many tiles the enemy has left after.
        self.assertEqual(17, simHost.sim.players[enemyGeneral.player].map.players[enemyGeneral.player].tileCount)
