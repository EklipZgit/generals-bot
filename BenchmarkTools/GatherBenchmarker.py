from __future__ import  annotations

import time
import typing
from enum import Enum

import logbook
import numpy as np

import Gather
from Gather import GatherCapturePlan
from Interfaces import MapMatrixInterface
from base.client.map import MapBase
from base.client.tile import Tile


NS_CONVERTER = (10 ** 9)

NO_ENTRY = (0, 0.0)


class GatherBenchScope(object):
    def __init__(self, gatherTypeKey: str, benchmarker: GatherBenchmarker):
        self.gather_key = gatherTypeKey
        self.gather_start_time: float = time.time_ns() / NS_CONVERTER
        self.gather_end_time: float | None = None
        self.parent: GatherBenchmarker = benchmarker
        self.gather_result: GatherBenchmarkResult | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.parent._complete_benchmark(self.gather_key, time.time_ns() / NS_CONVERTER - self.gather_start_time)



class GatherSort(Enum):
    Time = 1
    Value = 2
    RecalcDiff = 3


class GatherBenchmarker(object):
    def __init__(self):
        self.num_runs: int = 0
        self.runs: typing.List[str] = []
        self.cur_run_id: int = 0
        self.raw_results: typing.Dict[str, typing.List[GatherBenchmarkResult]] = {}
        self.gather_keys: typing.List[str] = []

        self._last_key: str = ''
        self._last_duration: float = 0.0

    def begin_next_run(self, runIdentifier: str) -> int:
        self.runs.append(runIdentifier)
        self.cur_run_id += 1
        self.num_runs += 1
        return self.cur_run_id
        
    def _get_or_create_gather_result_list(self, gatherTypeKey: str) -> typing.List[GatherBenchmarkResult]:
        gaths = self.raw_results.get(gatherTypeKey, None)

        if gaths is None:
            gaths = []
            self.raw_results[gatherTypeKey] = gaths
            self.gather_keys.append(gatherTypeKey)

        return gaths

    def begin_bench_gather(self, gatherKey: str) -> GatherBenchScope:
        """
        @param gatherKey:
        @return:
        """

        gatherBench = GatherBenchScope(gatherKey, self)
        
        return gatherBench

    def _complete_benchmark(self, gatherTypeKey: str, duration: float):
        self._last_key = gatherTypeKey
        self._last_duration = duration
        # curCount, curSumDuration = self.key_data.get(event_description, NO_ENTRY)
        # self.key_data[event_description] = (curCount + 1, curSumDuration + duration)

    def set_result_completion_data(
            self,
            map: MapBase,
            gcp: GatherCapturePlan,
            desiredTurns: int,
            valueMatrix: MapMatrixInterface[float],
            armyCostMatrix: MapMatrixInterface[float],
            negativeTiles: typing.Set[Tile] | None = None
    ):
        if self._last_key == '':
            raise Exception(f'you havent called with gathBenchmarker.begin_bench_gather(someKey): since the last call to set_result_completion_data...?')

        curList = self._get_or_create_gather_result_list(self._last_key)
        gathBenchResult = GatherBenchmarkResult(
            map,
            gcp,
            desiredTurns,
            self._last_duration,
            valueMatrix,
            armyCostMatrix,
            self.cur_run_id,
            negativeTiles=negativeTiles
        )
        curList.append(gathBenchResult)
        self._last_key = ''
        self._last_duration = 0.0

    def __str__(self) -> str:
        sortedStuff = self.get_data_info()
        return '\n'.join([str(entry) for entry in sortedStuff])

    def print_data_info(self, sortBy: GatherSort = GatherSort.Time, printRawOutput: bool = False):
        sortedStuff = self.get_data_info(sortBy, printRawOutput)
        logbook.info('\n' + '\n'.join([str(entry) for entry in sortedStuff]))

    def get_data_info(self, sortBy: GatherSort = GatherSort.Time, printRawOutput: bool = False) -> typing.List[GatherAggregateResults]:
        npAvgValsByTestRun = np.zeros(self.num_runs, dtype=np.float32)
        npAvgTurnsByTestRun = np.zeros(self.num_runs, dtype=np.float32)
        npMedianTurnsByTestRun = np.zeros(self.num_runs, dtype=np.float32)
        npAvgTimeByTestRun = np.zeros(self.num_runs, dtype=np.float32)
        npDesiredTurns = np.zeros(self.num_runs, dtype=np.int32)

        numGathTypes = len(self.gather_keys)
        for i in range(self.num_runs):
            totalGathVal = 0.0
            totalTurns = 0
            totalTimeMs = 0.0

            turns = []
            numWithValidResults = 0
            for gathKey in self.gather_keys:
                result = self.raw_results[gathKey][i]
                totalGathVal += result.recalculated_gather_val
                totalTurns += result.recalculated_length
                if result.recalculated_length > 1:
                    turns.append(result.recalculated_length)
                totalTimeMs += result.time_taken * 1000.0
                npDesiredTurns[i] = result.desired_turns

            if not turns:
                turns.append(1)

            npMedianTurnsByTestRun[i] = np.median(sorted(turns))

            avgGathVal = totalGathVal / numGathTypes
            avgGathTurns = totalTurns / numGathTypes
            avgGathTimeMs = totalTimeMs / numGathTypes

            npAvgValsByTestRun[i] = avgGathVal
            npAvgTurnsByTestRun[i] = avgGathTurns
            npAvgTimeByTestRun[i] = avgGathTimeMs
            if printRawOutput:
                logbook.info(f'for test run {i} {self.runs[i].ljust(20)} avgGathVal was {avgGathVal:.1f},            avgGathTurns was {avgGathTurns:.1f},          avgGathTime was {avgGathTimeMs:.1f}ms')
                for gathKey in self.gather_keys:
                    result = self.raw_results[gathKey][i]
                    npDesiredTurns[i] = result.desired_turns
                    logbook.info(f'    {gathKey.rjust(30)}:   gathVal was {result.reported_gather_val:.1f} (re {result.recalculated_gather_val:.1f}), gathTurns was {result.reported_length} (re {result.recalculated_length}),  gathTime was {result.time_taken * 1000.0:.1f}ms')

        npGatherVals = {}
        npGatherRecalcedVals = {}
        npGatherTurns = {}
        npGatherRecalcedTurns = {}
        npGatherTimes = {}
        npGatherRatioFromAvgVal = {}
        npGatherRatioFromMedTurns = {}
        npGatherRecalcDiffs = {}

        for gathKey in self.gather_keys:
            gathList = self.raw_results[gathKey]
            thisNpGathVals = np.zeros(self.num_runs, dtype=np.float32)
            thisNpGathTurns = np.zeros(self.num_runs, dtype=np.int32)
            thisNpRecalcedGathVals = np.zeros(self.num_runs, dtype=np.float32)
            thisNpRecalcedGathTurns = np.zeros(self.num_runs, dtype=np.int32)
            thisNpGathTimes = np.zeros(self.num_runs, dtype=np.float32)
            for i in range(self.num_runs):
                result = gathList[i]
                thisNpGathVals[i] = result.reported_gather_val
                thisNpRecalcedGathVals[i] = result.recalculated_gather_val
                thisNpGathTurns[i] = result.reported_length
                thisNpRecalcedGathTurns[i] = result.recalculated_length
                thisNpGathTimes[i] = result.time_taken * 1000.0

            npGatherVals[gathKey] = thisNpGathVals
            npGatherTurns[gathKey] = thisNpGathTurns
            npGatherRecalcedVals[gathKey] = thisNpRecalcedGathVals
            npGatherRecalcedTurns[gathKey] = thisNpRecalcedGathTurns
            npGatherTimes[gathKey] = thisNpGathTimes

            npGatherRatioFromAvgVal[gathKey] = thisNpRecalcedGathVals / npAvgValsByTestRun
            npGatherRatioFromMedTurns[gathKey] = thisNpRecalcedGathTurns / npMedianTurnsByTestRun
            npGatherRecalcDiffs[gathKey] = thisNpGathVals - thisNpRecalcedGathVals

        keysOrdered = self.gather_keys
        if sortBy == GatherSort.Time:
            keysOrdered = sorted(self.gather_keys, key=lambda k: np.mean(npGatherTimes[k]))
        elif sortBy == GatherSort.Value:
            keysOrdered = sorted(self.gather_keys, key=lambda k: np.mean(npGatherRecalcedVals[k] / npGatherRecalcedTurns[k]), reverse=True)
        elif sortBy == GatherSort.RecalcDiff:
            keysOrdered = sorted(self.gather_keys, key=lambda k: np.mean(np.abs(npGatherRecalcDiffs[k])), reverse=True)

        data = []

        for gathKey in keysOrdered:
            statsResult = GatherAggregateResults(gathKey)
            statsResult.average_gather_per_turn = np.mean(npGatherRecalcedVals[gathKey] / npGatherRecalcedTurns[gathKey])
            statsResult.val_vs_average_val = np.mean(npGatherRatioFromAvgVal[gathKey])
            statsResult.val_vs_average_val_std = np.std(npGatherRatioFromAvgVal[gathKey])

            timeRatios = npGatherTimes[gathKey] / npAvgTimeByTestRun
            statsResult.time_average = np.mean(npGatherTimes[gathKey])
            statsResult.time_vs_average_time = np.mean(timeRatios)
            statsResult.time_vs_average_time_std = np.std(timeRatios)

            statsResult.turns_vs_median_turns = np.mean(npGatherRatioFromMedTurns[gathKey])
            statsResult.turns_vs_median_turns_std = np.std(npGatherRatioFromMedTurns[gathKey])
            statsResult.turns_average_diff_from_median_abs = np.mean(np.abs(npGatherRecalcedTurns[gathKey] - npMedianTurnsByTestRun))
            statsResult.turns_average_diff_from_median = np.mean(npGatherRecalcedTurns[gathKey] - npMedianTurnsByTestRun)
            statsResult.turns_average_diff_from_median_std = np.std(npGatherRecalcedTurns[gathKey] - npMedianTurnsByTestRun)

            statsResult.val_vs_recalc_val = np.mean(np.abs(npGatherRecalcDiffs[gathKey]))
            statsResult.val_vs_recalc_val_no_abs = np.mean(npGatherRecalcDiffs[gathKey])

            data.append(statsResult)

        return data

    def undo_current_run(self):
        for key in self.gather_keys:
            l = self._get_or_create_gather_result_list(key)
            if len(l) >= self.cur_run_id:
                l.pop()
        self.cur_run_id -= 1
        self.num_runs -= 1
        if len(self.runs) >= self.cur_run_id:
            self.runs.pop()


class GatherAggregateResults(object):
    def __init__(self, gatherKey: str):
        self.gather_key: str = gatherKey

        self.time_average: float = 0.0

        self.time_vs_average_time: float = 0.0
        self.val_vs_average_val: float = 0.0
        self.average_gather_per_turn: float = 0.0

        self.val_vs_recalc_val: float = 0.0
        self.val_vs_recalc_val_no_abs: float = 0.0

        self.time_vs_average_time_std: float = 0.0
        self.val_vs_average_val_std: float = 0.0
        self.turns_average_diff_from_median_std: float = 0.0
        """Based on the standard deviation of the gathers result turns vs the avg turns"""

        self.turns_vs_median_turns: float = 0.0
        self.turns_vs_median_turns_std: float = 0.0
        self.turns_average_diff_from_median_abs: float = 0.0
        self.turns_average_diff_from_median: float = 0.0
        """Will show whether we shift positive or negative or normal"""

    def __str__(self) -> str:
        return f'{self.gather_key.rjust(30)} - gath: {self.average_gather_per_turn:6.2f}/t  {self.val_vs_average_val:5.3f}r σ {self.val_vs_average_val_std:.3f}r,   time: {self.time_average:5.2f}ms  {self.time_vs_average_time:6.3f}r σ {self.time_vs_average_time_std:6.3f}r,   turns: abs {self.turns_average_diff_from_median_abs:5.2f}t ({self.turns_average_diff_from_median:6.2f}t σ {self.turns_average_diff_from_median_std:5.3f}t)  {self.turns_vs_median_turns:5.3f}r σ {self.turns_vs_median_turns_std:.3f},   recalc diff avg {self.val_vs_recalc_val:.2f}  (no abs {self.val_vs_recalc_val_no_abs:.2f})'


class GatherBenchmarkResult(object):
    def __init__(
            self,
            map: MapBase,
            gcp: GatherCapturePlan,
            desiredTurns: int,
            timeTaken: float,
            valueMatrix: MapMatrixInterface[float],
            armyCostMatrix: MapMatrixInterface[float],
            testRunId: int,
            negativeTiles: typing.Set[Tile] | None = None
    ):
        self.test_run_id: int = testRunId

        self.recalculated_gather_val: float = 0.0
        self.recalculated_length: int = 0

        self.reported_gather_val: float = 0.0
        self.reported_length: int = 1

        if gcp is not None:
            self.reported_gather_val: float = gcp.gathered_army
            self.reported_length: int = gcp.length
            Gather.recalculate_tree_values_from_matrix([], gcp.root_nodes, valueMatrix, negativeTiles=negativeTiles)
            for node in gcp.root_nodes:
                self.recalculated_gather_val += node.value
                self.recalculated_length += node.gatherTurns

        # has to be at least 1 or we get divide by zero errors for not-found plans.
        self.reported_length = max(1, self.reported_length)
        self.recalculated_length = max(1, self.recalculated_length)

        self.time_taken: float = timeTaken

        # TODO iterate tree nodes and check if they go negative based on a recalculation from armyCostMatrix?
        self.produced_invalid_tile_crossings: bool = False

        self.desired_turns: int = desiredTurns


