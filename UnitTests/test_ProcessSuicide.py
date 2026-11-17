"""Regression tests for process-level suicide paths that must actually kill the process."""
import time
import unittest
from unittest import mock

import base.bot_base
from base.bot_base import GeneralsClientHost
from base.client.generals import GeneralsClient
from BotModules.WrpWorkerProcess import WrpRequest, WrpWorkerProcess


class ProcessSuicideTests(unittest.TestCase):
    """The suicide/killswitch threads must end the whole process, not just their own thread."""

    __slots__ = ()

    def test_suicide_thread_calls_os_exit_not_sys_exit(self) -> None:
        """sys.exit() in a daemon thread only kills that thread, leaving a zombie process.

        Live game log Human.exe-1v1-2026-11-12_11-35-36.txt: run() exited, the
        suicide thread logged 'ok, killing process', and the process then sat
        alive for ~10 hours because sys.exit() in a daemon thread is a no-op.
        """
        host = GeneralsClientHost.__new__(GeneralsClientHost)
        with mock.patch.object(base.bot_base.time, 'sleep'), \
                mock.patch.object(base.bot_base.os, '_exit') as os_exit, \
                mock.patch.object(base.bot_base.sys, 'exit') as sys_exit:
            host._suicide_in_4_seconds()

        os_exit.assert_called_once_with(0)
        sys_exit.assert_not_called()

    def test_killswitch_calls_os_exit_after_comms_silence(self) -> None:
        """The killswitch must end the whole process once comms have been dead."""
        client = GeneralsClient.__new__(GeneralsClient)
        client.lastCommunicationTime = time.time_ns() / (10 ** 9) - 3600.0
        client.map = None
        client.terminated = True
        client._running = False
        with mock.patch('base.client.generals.time.sleep'), \
                mock.patch('base.client.generals.os._exit') as os_exit, \
                mock.patch('base.client.generals.sys.exit') as sys_exit:
            client._start_killswitch_timer()

        os_exit.assert_called_once_with(2)
        sys_exit.assert_not_called()

    def test_wrp_worker_queues_do_not_join_feeder_threads_on_exit(self) -> None:
        """WRP queues must not block interpreter exit on a wedged worker.

        Live game log Human.exe-1v1-2026-11-12_11-35-36.txt: the worker stopped
        answering after generation 7 while submissions kept arriving, leaving the
        request_queue feeder thread blocked on a Windows pipe write. Python's
        Queue._finalize_join then joined that feeder with no timeout during
        interpreter shutdown, wedging the process for ~10 hours.
        """
        worker = WrpWorkerProcess()
        try:
            self.assertTrue(worker.request_queue._joincancelled)
            self.assertTrue(worker.result_queue._joincancelled)
        finally:
            worker.close()

    @staticmethod
    def _dummy_request() -> WrpRequest:
        """A structurally valid request; submit() rejects closed/closing workers
        before the payload is ever unpickled, so contents are never used."""
        return WrpRequest(
            generation=1, map_payload=b'', start_tile_index=0,
            target_tile_indexes=[], initial_army=0, time_limit=0.01)

    def test_wrp_worker_request_close_polls_to_closed(self) -> None:
        """Async FFA-end close: request_close is non-blocking, poll_close
        finalizes once the daemon worker self-exits, submit is rejected while
        closing, and request_close on a never-started worker leaves nothing
        unclosable. Idempotent with the blocking game-over close()."""
        # never-started worker: request_close finalizes immediately (no process
        # to join, no unclosable queues) and submit stays rejected.
        idle = WrpWorkerProcess()
        idle.request_close()
        self.assertTrue(idle.closed)
        self.assertTrue(idle.poll_close())
        with self.assertRaises(RuntimeError):
            idle.submit(self._dummy_request())

        # running worker: launch the real process exactly as submit() does but
        # without a WRP job - _wrp_worker_main blocks on request_queue.get()
        # until the None sentinel request_close() enqueues.
        worker = WrpWorkerProcess()
        worker.started = True
        worker.process.start()
        try:
            worker.request_close()
            self.assertFalse(worker.closed)          # non-blocking: still closing
            self.assertTrue(worker.close_requested)
            # submit while closing must be rejected - never enqueue behind None
            with self.assertRaises(RuntimeError):
                worker.submit(self._dummy_request())
            # bounded poll until the daemon self-exits on its own
            deadline = time.time() + 15.0
            closed = False
            while time.time() < deadline:
                if worker.poll_close(timeout_sec=0.05):
                    closed = True
                    break
                time.sleep(0.01)
            self.assertTrue(closed, "WRP worker did not self-terminate after request_close")
            # game-over close() after async close is a safe no-op
            worker.close()
            self.assertTrue(worker.closed)
        finally:
            if not worker.closed:
                worker.close()


if __name__ == "__main__":
    unittest.main()
