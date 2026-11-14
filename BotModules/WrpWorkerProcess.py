"""Process-isolated watchman-route work for live bot moves."""

from __future__ import annotations

import multiprocessing
import pickle
import time
from dataclasses import dataclass
from multiprocessing.context import BaseContext
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue as ProcessQueue
from queue import Empty

from Algorithms import WatchmanRouteUtils
from DistanceMapperImpl import DistanceMapperImpl
from base.client.map import MapBase


@dataclass(slots=True)
class WrpRequest:
    """Serializable WRP request containing a caller-pickled map snapshot."""

    generation: int
    map_payload: bytes
    start_tile_index: int
    target_tile_indexes: list[int]
    initial_army: int
    time_limit: float


@dataclass(slots=True)
class WrpResult:
    """Index-only WRP result safe to return from the worker process."""

    generation: int
    tile_indexes: list[int] | None
    duration_sec: float


def _wrp_worker_main(
    request_queue: ProcessQueue,
    result_queue: ProcessQueue,
) -> None:
    """Run only the newest queued WRP request in this daemon process."""
    while True:
        request = request_queue.get()
        if request is None:
            return
        if not isinstance(request, WrpRequest):
            raise TypeError(f"Unexpected WRP request type: {type(request)}")

        while True:
            try:
                newer_request = request_queue.get_nowait()
            except Empty:
                break
            if newer_request is None:
                return
            if not isinstance(newer_request, WrpRequest):
                raise TypeError(
                    f"Unexpected WRP request type: {type(newer_request)}")
            request = newer_request

        start_time = time.perf_counter()
        game_map = pickle.loads(request.map_payload)
        if not isinstance(game_map, MapBase):
            raise TypeError(f"Expected MapBase, got {type(game_map)}")
        game_map.distance_mapper = DistanceMapperImpl(game_map)
        start_tile = game_map.tiles_by_index[request.start_tile_index]
        target_tiles = [
            game_map.tiles_by_index[tile_index]
            for tile_index in request.target_tile_indexes]
        path = WatchmanRouteUtils.get_watchman_path(
            game_map,
            start_tile,
            target_tiles,
            timeLimit=request.time_limit,
            initialArmy=request.initial_army)
        tile_indexes = (
            [tile.tile_index for tile in path.tileList]
            if path is not None
            else None)
        result_queue.put(WrpResult(
            generation=request.generation,
            tile_indexes=tile_indexes,
            duration_sec=time.perf_counter() - start_time))


class WrpWorkerProcess:
    """Own a lazily started spawn-context WRP worker and its queues."""

    __slots__ = (
        "context",
        "request_queue",
        "result_queue",
        "process",
        "started",
        "closed",
    )

    def __init__(self) -> None:
        self.context: BaseContext = multiprocessing.get_context("spawn")
        self.request_queue: ProcessQueue = self.context.Queue()
        self.result_queue: ProcessQueue = self.context.Queue()
        # UnitTests/test_ProcessSuicide.py::test_wrp_worker_queues_do_not_join_feeder_threads_on_exit
        # Python joins queue feeder threads with no timeout during interpreter
        # shutdown; a wedged or dead worker leaves the pipe undrained and that join
        # blocks the exit forever (the ~10h zombie after Human.exe-1v1
        # 2026-11-12_11-35-36). The worker is a daemon child and queued work is
        # disposable at exit, so never join these feeders.
        self.request_queue.cancel_join_thread()
        self.result_queue.cancel_join_thread()
        self.process: BaseProcess = self.context.Process(
            target=_wrp_worker_main,
            args=(self.request_queue, self.result_queue),
            daemon=True)
        self.started = False
        self.closed = False

    def submit(self, request: WrpRequest) -> None:
        """Start the worker on first use and submit one WRP request."""
        if self.closed:
            raise RuntimeError("Cannot submit WRP work to a closed worker")
        if not self.started:
            self.started = True
            self.process.start()
        elif not self.process.is_alive():
            raise RuntimeError("WRP worker process exited before new work was submitted")
        self.request_queue.put(request)

    def get_results_nowait(self) -> list[WrpResult]:
        """Drain all currently available worker results without blocking."""
        if not self.started:
            return []
        results: list[WrpResult] = []
        while True:
            try:
                result = self.result_queue.get_nowait()
            except Empty:
                return results
            if not isinstance(result, WrpResult):
                raise TypeError(f"Unexpected WRP result type: {type(result)}")
            results.append(result)

    def is_alive(self) -> bool:
        """Return whether the lazily started worker process is alive."""
        return self.started and self.process.is_alive()

    def close(self, timeout_sec: float = 30.0) -> None:
        """Stop the worker for deterministic process-backed unit-test cleanup."""
        if self.closed:
            return
        if self.started and self.process.is_alive():
            self.request_queue.put(None)
            self.process.join(timeout_sec)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout_sec)
                self.closed = True
                raise RuntimeError("WRP worker process did not stop after shutdown")
        if self.started:
            self.process.close()
        self.request_queue.close()
        self.result_queue.close()
        self.closed = True
