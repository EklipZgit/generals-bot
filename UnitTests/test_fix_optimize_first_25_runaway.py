import time
import unittest

import EarlyExpandUtils
from Tests.TestBase import TestBase
from base.client.map import MapBase


class OptimizeFirst25RunawaySearchTests(TestBase):
    """
    Repro for the multi-second FFA turn stall: in
    Human.exe-ffa-2026-09-30_03-58-31---gF1m5rDW9 the scope
    'EXP - first25 reuse - 0.0730' (caller had ~73ms of move budget remaining)
    logged 'Complete t74: (24.1267) optimize_first_25' and starved the viewer
    socket for 12+ seconds.

    Root cause: _sub_optimize_first_25_specific_wasted only checked cutoff_time
    BETWEEN forced-move iterations, and _optimize_25_launch_segment ran
    breadth_first_dynamic_max with a hardcoded maxTime=1000, so a single
    segment search could overrun the caller's remaining budget unboundedly.
    """

    def __init__(self, methodName: str = 'runTest'):
        super().__init__(methodName)
        MapBase.DO_NOT_RANDOMIZE = True

    def _load_map_inputs(self):
        map, general = self.load_turn_1_map_and_general('EarlyExpandUtilsTestMaps/exploded_turn_19.txtmap')
        self.get_tiles_capped_on_50_count_and_reset_map(map, general)
        weightMap = self.get_opposite_general_distance_map(map, general)
        distToGenMap = map.distance_mapper.get_tile_dist_matrix(general)
        return map, general, weightMap, distToGenMap

    def test_launch_segment_returns_immediately_when_cutoff_already_expired(self):
        map, general, weightMap, distToGenMap = self._load_map_inputs()

        start = time.perf_counter()
        EarlyExpandUtils._optimize_25_launch_segment(
            map,
            general,
            20,
            50 - map.turn,
            distToGenMap,
            force_wasted_moves=0,
            tile_weight_map=weightMap,
            visited_set=set(),
            cutoff_time=start,  # already expired: caller has zero remaining budget
            no_log=True)

        self.assertLess(
            time.perf_counter() - start,
            1.0,
            'segment search must honor an already-expired caller cutoff instead of running the full hardcoded maxTime')

    def test_launch_segment_still_searches_with_generous_cutoff(self):
        map, general, weightMap, distToGenMap = self._load_map_inputs()

        path = EarlyExpandUtils._optimize_25_launch_segment(
            map,
            general,
            20,
            50 - map.turn,
            distToGenMap,
            force_wasted_moves=0,
            tile_weight_map=weightMap,
            visited_set=set(),
            cutoff_time=time.perf_counter() + 60.0,
            no_log=True)

        self.assertIsNotNone(path, 'a healthy time budget must still produce the same search results as no cutoff')

    def test_optimize_first_25_respects_nearly_expired_cutoff(self):
        map, general, weightMap, _ = self._load_map_inputs()

        start = time.perf_counter()
        EarlyExpandUtils.optimize_first_25(
            map,
            general,
            weightMap,
            cutoff_time=start + 0.05,
            no_log=True)

        self.assertLess(
            time.perf_counter() - start,
            2.0,
            'optimize_first_25 must not run multi-second unbounded segment searches after the caller budget is spent')


if __name__ == '__main__':
    unittest.main()
