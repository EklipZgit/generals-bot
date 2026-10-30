import typing

import Gather
from MapMatrix import MapMatrix
from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile


class GatherMaxIterativeSetRemoveNodeFixTests(TestBase):
    """
    Reproduction for a live-game crash observed in 1v1 game
    Human.exe-1v1-2026-09-30_05-09-15---S_d8HGVge (repeated every turn t368-t387):

      File "Gather/GatherMaxIterativeSet.py", line 1404, in
          prune_set_to_turns_and_reconnect_with_values
      File "Gather/GatherMaxIterativeSet.py", line 1104, in
          prune_set_by_articulation_points
          nxForBcc.remove_node(t.tile_index)
      networkx.exception.NetworkXError: The node 267 is not in the graph.

    Root cause: toPrune can contain tiles whose isObstacle is True - mountains,
    undiscovered obstacles, and costly neutrals (neutral army > PATHABLE_CITY_THRESHOLD,
    e.g. neutral cities that gather plans target for capture).
    prune_set_to_turns_and_reconnect_with_values already anticipates this via its
    'non-pathable/undiscovered tile(s) in toPrune' diagnostic. But
    build_networkX_graph_no_obstacles_no_weights skips isObstacle tiles entirely, so
    those tiles are seeded into dcQueue while never being inserted as nxForBcc nodes.
    They can never appear in unsafeToCut (it only contains graph node indices), so the
    first time such a tile pops it falls straight through to remove_node and crashes -
    deterministically, every turn, which matches the repeated live-game failure.

    These tests feed an isObstacle tile (mountain / costly neutral city) through
    prune_set_by_articulation_points in toPrune and assert it is pruned cleanly.
    """

    def test_prune_set_by_articulation_points_handles_mountain_in_toPrune(self):
        testData = """
|    |    |    |
aG1  a1   M    a1
a1   a1   a1   bG1
|    |    |    |
player_index=0
        """
        map, _, _ = self.load_map_and_generals_from_string(testData, 100)
        mountain = map.GetTile(2, 0)
        self.assertTrue(mountain.isObstacle)

        toPrune: typing.Set[Tile] = {
            mountain,
            map.GetTile(1, 0),
            map.GetTile(3, 0),
            map.GetTile(1, 1),
        }
        valueMatrix = MapMatrix(map, 1.0)
        armyCostMatrix = MapMatrix(map, 1.0)
        pruneReconnectCountMatrix = MapMatrix(map, 0)

        # pre-fix this raised NetworkXError: mountain has army 0 so it is the lowest
        # heap entry, it can never be an articulation point (it is not a graph node),
        # so it fell through to nxForBcc.remove_node on a missing node
        currentGathVal, currentArmySum, pruned = Gather.prune_set_by_articulation_points(
            map,
            set(),
            toPrune,
            2,
            valueMatrix,
            armyCostMatrix,
            pruneReconnectCountMatrix,
            4.0,
            4.0,
            None)

        self.assertIn(mountain, pruned)
        self.assertEqual(2, len(pruned))
        self.assertEqual(2, len(toPrune))
        self.assertNotIn(mountain, toPrune)
        self.assertEqual(2.0, currentGathVal)
        self.assertEqual(2.0, currentArmySum)

    def test_prune_set_by_articulation_points_handles_costly_neutral_city_in_toPrune(self):
        """
        Neutral cities (isNeutral and army > PATHABLE_CITY_THRESHOLD) are isObstacle,
        and are the most likely live-game culprit: gather plans deliberately include
        cities as capture targets, so a costly neutral city can ride along in
        reconnectedSubset into prune_set_by_articulation_points.
        """
        testData = """
|    |    |    |
aG1  a1   C40  a1
a1   a1   a1   bG1
|    |    |    |
player_index=0
        """
        map, _, _ = self.load_map_and_generals_from_string(testData, 100)
        city = map.GetTile(2, 0)
        self.assertTrue(city.isCity)
        self.assertTrue(city.isObstacle)

        toPrune: typing.Set[Tile] = {
            city,
            map.GetTile(1, 0),
            map.GetTile(3, 0),
            map.GetTile(1, 1),
        }
        valueMatrix = MapMatrix(map, 1.0)
        # give the city the lowest gather value so it is the first dcQueue pop
        valueMatrix.raw[city.tile_index] = 0.0
        armyCostMatrix = MapMatrix(map, 1.0)
        pruneReconnectCountMatrix = MapMatrix(map, 0)

        # pre-fix this raised NetworkXError on the very first pop: the city is not an
        # articulation point (not even a graph node) so it went to remove_node directly
        currentGathVal, currentArmySum, pruned = Gather.prune_set_by_articulation_points(
            map,
            set(),
            toPrune,
            2,
            valueMatrix,
            armyCostMatrix,
            pruneReconnectCountMatrix,
            4.0,
            4.0,
            None)

        self.assertIn(city, pruned)
        self.assertEqual(2, len(pruned))
        self.assertEqual(2, len(toPrune))
        self.assertNotIn(city, toPrune)
        # the city (value 0.0) and one 1.0-value tile are pruned out of the 4.0 total
        self.assertEqual(3.0, currentGathVal)
        self.assertEqual(2.0, currentArmySum)
