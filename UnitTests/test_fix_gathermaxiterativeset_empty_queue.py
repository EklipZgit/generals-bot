import typing
import unittest

import Gather
from MapMatrix import MapMatrix
from TestBase import TestBase
from base.client.map import MapBase
from base.client.tile import Tile


class GatherMaxIterativeSetEmptyQueueFixTests(TestBase):
    """
    Regression for a latent IndexError in
    GatherMaxIterativeSet.prune_set_by_articulation_points.

    The prune loop drains dcQueue of prune candidates, parking articulation
    points in unableToPrune and re-queuing them via refreshUnableToPrune when
    the queue empties. But refreshUnableToPrune can only re-queue parked tiles
    that are still in toPrune, so the queue can legitimately remain empty:

      - every toPrune member is a rootTile (dcQueue seeds empty), or
      - unableToPrune is empty / all parked members were already pruned via
        stale duplicate dcQueue entries (see the `t not in toPrune` skip added
        in test_fix_gathermaxiterativeset_remove_node).

    In those cases the lastPrunedToUnsafe no-progress check does not fire on the
    first drain (it requires a second drain at the same size), so
    heapq.heappop ran on an empty heap and raised IndexError.
    """

    def test_prune_set_by_articulation_points_all_roots_does_not_heappop_empty(self):
        testData = """
|    |    |    |
aG1  a1   a1   a1
a1   a1   a1   bG1
|    |    |    |
player_index=0
        """
        map, _, _ = self.load_map_and_generals_from_string(testData, 100)

        # every member of toPrune is a root tile -> dcQueue seeds empty
        rootTiles: typing.Set[Tile] = {map.GetTile(1, 0), map.GetTile(2, 0)}
        toPrune: typing.Set[Tile] = set(rootTiles)

        valueMatrix = MapMatrix(map, 1.0)
        armyCostMatrix = MapMatrix(map, 1.0)
        pruneReconnectCountMatrix = MapMatrix(map, 0)

        # pre-fix: `not dcQueue` -> refreshUnableToPrune pushes nothing ->
        # heapq.heappop(dcQueue) raised IndexError: index out of range
        currentGathVal, currentArmySum, pruned = Gather.prune_set_by_articulation_points(
            map,
            rootTiles,
            toPrune,
            1,
            valueMatrix,
            armyCostMatrix,
            pruneReconnectCountMatrix,
            2.0,
            2.0,
            None)

        # root tiles must never be pruned; nothing could be dequeued
        self.assertEqual([], pruned)
        self.assertEqual(2, len(toPrune))
        self.assertEqual(2.0, currentGathVal)
        self.assertEqual(2.0, currentArmySum)

    def test_prune_set_by_articulation_points_still_prunes_normally(self):
        testData = """
|    |    |    |
aG1  a1   a1   a1
a1   a1   a1   bG1
|    |    |    |
player_index=0
        """
        map, _, _ = self.load_map_and_generals_from_string(testData, 100)

        rootTiles: typing.Set[Tile] = {map.GetTile(1, 0)}
        toPrune: typing.Set[Tile] = {
            map.GetTile(1, 0),
            map.GetTile(2, 0),
            map.GetTile(3, 0),
            map.GetTile(2, 1),
        }

        valueMatrix = MapMatrix(map, 1.0)
        armyCostMatrix = MapMatrix(map, 1.0)
        pruneReconnectCountMatrix = MapMatrix(map, 0)

        currentGathVal, currentArmySum, pruned = Gather.prune_set_by_articulation_points(
            map,
            rootTiles,
            toPrune,
            2,
            valueMatrix,
            armyCostMatrix,
            pruneReconnectCountMatrix,
            4.0,
            4.0,
            None)

        self.assertEqual(2, len(toPrune))
        self.assertIn(map.GetTile(1, 0), toPrune)
        self.assertEqual(2, len(pruned))


if __name__ == '__main__':
    unittest.main()
