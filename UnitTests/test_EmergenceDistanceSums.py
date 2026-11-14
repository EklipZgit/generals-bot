import math

import ArmyTracker as ArmyTrackerModule
from ArmyTracker import ArmyTracker
from TestBase import TestBase
from base.client.map import MapBase


class EmergenceDistanceSumsTests(TestBase):
    def __init__(self, methodName: str = ...):
        """Initialize map-island identifiers deterministically for this test suite."""
        MapBase.DO_NOT_RANDOMIZE = True
        super().__init__(methodName)

    def _load_test_map(self) -> tuple[MapBase, ArmyTracker]:
        """Load a deterministic open 3x3 map with two general positions."""
        rawMap = """|  |  |  |
aG1      bG1
         
         
|  |  |  |
aTiles=1
bTiles=1
"""
        gameMap, _ = self.load_map_and_general_from_string(
            rawMap,
            turn=200,
            player_index=0)
        for tile in gameMap.tiles_by_index:
            tile.visible = False
            tile.discovered = False
        return gameMap, ArmyTracker(gameMap)

    @staticmethod
    def _restore_bonus_enabled(enabled: bool) -> None:
        """Restore the module-level bonus switch after a test."""
        ArmyTrackerModule.EMERGENCE_DISTANCE_BONUS_ENABLED = enabled

    def test_two_emergence_sources_accumulate_exact_distances(self):
        """Verify true distance sums and reach counts for two sources."""
        gameMap, tracker = self._load_test_map()
        firstSource = gameMap.At(0, 1)
        secondSource = gameMap.At(2, 1)
        target = gameMap.At(1, 2)
        tracker.uneliminated_emergence_events[1][firstSource] = 4
        tracker.uneliminated_emergence_events[1][secondSource] = 4

        distanceSums = tracker.get_emergence_distance_sums(1)

        # The BFS starts at source neighbors with dist 0, so this diagonal tile is
        # at true distance 2 from each source: distance_sum=4 and reach_count=2.
        self.assertEqual(4, distanceSums.distance_sum.raw[target.tile_index])
        self.assertEqual(2, distanceSums.reach_count.raw[target.tile_index])

    def test_relimit_counts_full_distance_without_extending_elimination(self):
        """Keep elimination bounded while accumulating distances across the whole map."""
        gameMap, tracker = self._load_test_map()
        source = gameMap.At(0, 1)
        nearTile = gameMap.At(0, 2)
        farTile = gameMap.At(2, 2)
        tracker.uneliminated_emergence_events[1][source] = 2
        validPositions = tracker.valid_general_positions_by_player[1]
        for tile in gameMap.tiles_by_index:
            validPositions.raw[tile.tile_index] = (
                not tile.isObstacle and not tile.isGeneral)

        tracker.re_limit_player_gen_locations(
            1,
            tracker.uneliminated_emergence_events[1])

        distanceSums = tracker.emergence_distance_sums_by_player[1]
        # With maxDist=2 the source neighbor is kept, but the diagonal far tile
        # has true distance 3 and is eliminated even though the unbounded BFS records it.
        self.assertTrue(validPositions.raw[nearTile.tile_index])
        self.assertFalse(validPositions.raw[farTile.tile_index])
        self.assertEqual(3, distanceSums.distance_sum.raw[farTile.tile_index])
        self.assertEqual(1, distanceSums.reach_count.raw[farTile.tile_index])

    def test_discovered_neutral_wall_blocks_sources(self):
        """Treat unreachable emergence sources as neutral-distance contributors."""
        gameMap, tracker = self._load_test_map()
        leftSource = gameMap.At(0, 1)
        rightSource = gameMap.At(2, 1)
        target = gameMap.At(2, 2)
        tracker.unrecaptured_emergence_events[1].update(
            {leftSource, rightSource})
        for y in range(3):
            wallTile = gameMap.At(1, y)
            wallTile.discoveredAsNeutral = True
            tracker.tiles_ever_owned_by_player[1].discard(wallTile)

        distanceSums = tracker.get_emergence_distance_sums(1)
        bonusMatrix = tracker.build_emergence_distance_bonus_matrix(1, 10)

        # The left source visits the neutral wall but cannot expand through it;
        # the right source reaches this adjacent tile at true distance 1.
        self.assertEqual(1, distanceSums.reach_count.raw[target.tile_index])
        self.assertEqual(1, distanceSums.distance_sum.raw[target.tile_index])
        # The blocked source contributes D=10, leaving 20-(1+10)=9 and bonus 3.
        self.assertEqual(3.0, bonusMatrix.raw[target.tile_index])

    def test_accessor_adds_sources_and_rebuilds_after_removal(self):
        """Incrementally include added sources and rebuild after removing a source."""
        gameMap, tracker = self._load_test_map()
        firstSource = gameMap.At(0, 1)
        secondSource = gameMap.At(2, 1)
        target = gameMap.At(1, 1)
        tracker.unrecaptured_emergence_events[1].add(firstSource)

        firstSums = tracker.get_emergence_distance_sums(1)
        self.assertEqual(1, firstSums.distance_sum.raw[target.tile_index])
        self.assertEqual(1, firstSums.reach_count.raw[target.tile_index])

        tracker.unrecaptured_emergence_events[1].add(secondSource)
        addedSums = tracker.get_emergence_distance_sums(1)
        self.assertEqual(2, addedSums.distance_sum.raw[target.tile_index])
        self.assertEqual(2, addedSums.reach_count.raw[target.tile_index])

        tracker.unrecaptured_emergence_events[1].remove(secondSource)
        rebuiltSums = tracker.get_emergence_distance_sums(1)
        self.assertEqual(1, rebuiltSums.distance_sum.raw[target.tile_index])
        self.assertEqual(1, rebuiltSums.reach_count.raw[target.tile_index])

    def test_bonus_matrix_formula_and_disable_flag(self):
        """Check the distance bonus formula and runtime feature switch."""
        gameMap, tracker = self._load_test_map()
        firstSource = gameMap.At(0, 1)
        secondSource = gameMap.At(2, 1)
        firstTarget = gameMap.At(1, 1)
        secondTarget = gameMap.At(1, 2)
        tracker.uneliminated_emergence_events[1][firstSource] = 4
        tracker.uneliminated_emergence_events[1][secondSource] = 4
        distanceSums = tracker.emergence_distance_sums_by_player[1]
        distanceSums.source_tiles.update({firstSource, secondSource})
        distanceSums.distance_sum.raw[firstTarget.tile_index] = 5
        distanceSums.reach_count.raw[firstTarget.tile_index] = 2
        distanceSums.distance_sum.raw[secondTarget.tile_index] = 2
        distanceSums.reach_count.raw[secondTarget.tile_index] = 1

        bonusMatrix = tracker.build_emergence_distance_bonus_matrix(1, 10)

        self.assertAlmostEqual(
            math.sqrt(15),
            bonusMatrix.raw[firstTarget.tile_index])
        self.assertAlmostEqual(
            math.sqrt(8),
            bonusMatrix.raw[secondTarget.tile_index])

        originalFlag = ArmyTrackerModule.EMERGENCE_DISTANCE_BONUS_ENABLED
        self.addCleanup(self._restore_bonus_enabled, originalFlag)
        ArmyTrackerModule.EMERGENCE_DISTANCE_BONUS_ENABLED = False
        disabledBonus = tracker.build_emergence_distance_bonus_matrix(1, 10)
        self.assertTrue(all(value == 0 for value in disabledBonus.raw))
