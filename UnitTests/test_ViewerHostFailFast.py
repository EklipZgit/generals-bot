"""Regression tests for viewer initialization and process-exit handling."""
import queue
import time
import unittest
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue
from typing import Any, cast

from Viewer.ViewerProcessHost import ViewerHost


class FakeProcess:
    """Expose process liveness without starting a child process."""

    __slots__ = ("_alive",)

    def __init__(self, alive: bool) -> None:
        """Initialize the process liveness state."""
        self._alive = alive

    def is_alive(self) -> bool:
        """Return whether this fake process is alive."""
        return self._alive


def make_viewer_host(
        alive: bool,
        events: queue.Queue[tuple[str, Any]] | None = None) -> ViewerHost:
    """Create a ViewerHost with only the state used by the fail-fast paths."""
    viewer = cast(ViewerHost, ViewerHost.__new__(ViewerHost))
    viewer._bypass = False
    viewer._started = True
    viewer._recieved_init_ack = False
    viewer._closed_by_user = None
    viewer.on_click = None
    event_queue = events if events is not None else queue.Queue()
    viewer._viewer_event_queue = cast(Queue[tuple[str, Any]], event_queue)
    viewer.process = cast(BaseProcess, FakeProcess(alive))
    return viewer


class ViewerHostFailFastTests(unittest.TestCase):
    """Verify dead viewers cannot stall initialization or move handling."""

    __slots__ = ()

    def test_dead_process_fails_initialization_immediately(self) -> None:
        """Initialization does not wait for the full timeout after process exit."""
        viewer = make_viewer_host(alive=False)
        start_time = time.perf_counter()

        with self.assertRaisesRegex(
                Exception,
                "VIEWER PROCESS EXITED BEFORE INITIALIZING"):
            viewer.wait_viewer_initialized()

        self.assertLess(time.perf_counter() - start_time, 2.0)

    def test_closed_event_fails_initialization_immediately(self) -> None:
        """A CLOSED event records its reason and aborts initialization."""
        events: queue.Queue[tuple[str, Any]] = queue.Queue()
        events.put(("CLOSED", False))
        viewer = make_viewer_host(alive=True, events=events)
        start_time = time.perf_counter()

        with self.assertRaisesRegex(
                Exception,
                "VIEWER CLOSED BEFORE INITIALIZING"):
            viewer.wait_viewer_initialized()

        self.assertFalse(viewer._closed_by_user)
        self.assertLess(time.perf_counter() - start_time, 2.0)

    def test_has_viewer_exited_tracks_process_liveness(self) -> None:
        """The host reports dead processes and ignores healthy empty queues."""
        dead_viewer = make_viewer_host(alive=False)
        live_viewer = make_viewer_host(alive=True)

        self.assertTrue(dead_viewer.has_viewer_exited())
        self.assertFalse(live_viewer.has_viewer_exited())


if __name__ == "__main__":
    unittest.main()
