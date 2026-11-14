"""Regression tests for idle queue cancellation in GeneralsClient."""
import threading
import time
import unittest
from collections import deque
from dataclasses import dataclass
from typing import cast

from websocket import WebSocketTimeoutException

import base.client.generals as generals
from base.client.generals import GeneralsClient


@dataclass(slots=True)
class FakeWebSocketStep:
    """One scripted message or wait step for a fake websocket."""

    message: str | None = None
    is_timeout: bool = False
    delay_seconds: float = 0.0


class FakeWebSocket:
    """Record sends and provide messages and timeout events to get_updates."""

    __slots__ = (
        "steps",
        "timeout",
        "sent_messages",
        "sent_times",
        "timeout_values",
        "closed",
    )

    def __init__(self, steps: list[FakeWebSocketStep]) -> None:
        """Initialize scripted websocket steps and observable socket state."""
        self.steps: deque[FakeWebSocketStep] = deque(steps)
        self.timeout: float | None = None
        self.sent_messages: list[str] = []
        self.sent_times: list[float] = []
        self.timeout_values: list[float | None] = []
        self.closed = False

    def recv(self) -> str:
        """Return messages, wait through no-timeout steps, or raise socket timeouts."""
        while self.steps:
            step = self.steps.popleft()
            if step.is_timeout:
                if self.timeout is None:
                    time.sleep(step.delay_seconds)
                    continue
                time.sleep(step.delay_seconds if step.delay_seconds > 0.0 else self.timeout)
                raise WebSocketTimeoutException("scripted timeout")
            if step.delay_seconds > 0.0:
                time.sleep(step.delay_seconds)
            if step.message is None:
                raise ValueError("A non-timeout fake websocket step needs a message")
            return step.message

        if self.timeout is not None:
            time.sleep(self.timeout)
        raise WebSocketTimeoutException("script exhausted")

    def send(self, message: str) -> None:
        """Record a websocket message and its send time."""
        self.sent_messages.append(message)
        self.sent_times.append(time.perf_counter())

    def settimeout(self, timeout: float | None) -> None:
        """Record and apply the socket receive timeout."""
        self.timeout = timeout
        self.timeout_values.append(timeout)

    def close(self) -> None:
        """Record that the websocket was closed."""
        self.closed = True


def make_client(steps: list[FakeWebSocketStep]) -> tuple[GeneralsClient, FakeWebSocket]:
    """Build a client without opening a network connection."""
    client = cast(GeneralsClient, GeneralsClient.__new__(GeneralsClient))
    websocket = FakeWebSocket(steps)
    client._ws = websocket
    client._lock = threading.RLock()
    client.logFile = None
    client.earlyLogs = []
    client.lastCommunicationTime = time.time()
    client._seen_update = False
    client.terminated = False
    client._running = True
    client.start_data = {}
    client._currentQueue = {}
    client._queue_wait_start_time = time.perf_counter()
    client.queue_idle_timeout_seconds = 0.0
    client.queue_cancel_game_start_grace_seconds = 0.3
    client._queue_cancel_deadline = None
    client._game_starting = False
    client.game_start_update_timeout_seconds = 0.4
    client._game_start_deadline = None
    return client, websocket


class GeneralsClientQueueCancelTests(unittest.TestCase):
    """Verify idle queue cancellation while preserving newly formed games."""

    __slots__ = ()

    def test_idle_queue_timeout_sends_cancel_then_terminates_after_grace(self) -> None:
        """An idle client cancels once and waits the full game-start grace."""
        grace_seconds = 0.3
        client, websocket = make_client([
            FakeWebSocketStep(message="2"),
        ])
        client.queue_cancel_game_start_grace_seconds = grace_seconds

        with self.assertRaisesRegex(
                ValueError,
                "Left queue after idling too long; no game start within grace period"):
            next(client.get_updates())

        self.assertEqual(websocket.sent_messages, ['42["cancel"]'])
        self.assertEqual(len(websocket.sent_times), 1)
        self.assertGreaterEqual(
            time.perf_counter() - websocket.sent_times[0],
            grace_seconds)

    def test_game_start_after_cancel_is_played(self) -> None:
        """A pre-game start during the grace period cancels the pending exit."""
        client, websocket = make_client([
            FakeWebSocketStep(message="2"),
            FakeWebSocketStep(message='42["pre_game_start"]'),
            FakeWebSocketStep(
                is_timeout=True,
                delay_seconds=0.35),
            FakeWebSocketStep(
                message='42["game_update", {"turn": 1}]'),
        ])

        self.assertEqual(
            next(client.get_updates()),
            ("game_update", {"turn": 1}))
        self.assertGreater(0.35, client.queue_cancel_game_start_grace_seconds)
        self.assertIn(None, websocket.timeout_values)

    def test_chatty_queue_still_terminates_after_grace(self) -> None:
        """Frequent queue updates cannot extend the cancellation grace period."""
        client, websocket = make_client([
            FakeWebSocketStep(message="2"),
            *[
                FakeWebSocketStep(
                    message='42["queue_update", {}]',
                    delay_seconds=0.025)
                for _ in range(20)
            ],
        ])

        with self.assertRaisesRegex(
                ValueError,
                "Left queue after idling too long; no game start within grace period"):
            next(client.get_updates())

        self.assertEqual(websocket.sent_messages, ['42["cancel"]'])

    def test_idle_queue_cancels_without_any_heartbeats(self) -> None:
        """An idle queue deadline cancels even when the server sends no heartbeat."""
        idle_timeout_seconds = 0.2
        client, websocket = make_client([])
        client.queue_idle_timeout_seconds = idle_timeout_seconds
        client.queue_cancel_game_start_grace_seconds = 0.3
        start_time = time.perf_counter()

        with self.assertRaisesRegex(
                ValueError,
                "Left queue after idling too long"):
            next(client.get_updates())

        self.assertEqual(websocket.sent_messages, ['42["cancel"]'])
        self.assertGreaterEqual(
            websocket.sent_times[0] - start_time,
            idle_timeout_seconds)

    def test_idle_queue_deadline_anchored_to_queue_wait_start_not_get_updates_call(
            self) -> None:
        """Queue time spent before get_updates counts toward the idle deadline."""
        client, websocket = make_client([
            FakeWebSocketStep(message='42["queue_update", {}]'),
        ])
        client.queue_idle_timeout_seconds = 540.0
        client._queue_wait_start_time = time.perf_counter() - 1000.0

        with self.assertRaisesRegex(
                ValueError,
                "Left queue after idling too long"):
            next(client.get_updates())

        self.assertEqual(websocket.sent_messages, ['42["cancel"]'])

    def test_pre_game_start_without_game_update_terminates(self) -> None:
        """A pre_game_start that never produces a game_update must not wait forever.

        The server can abort a forming match back into the queue; _game_starting
        must not permanently disable the client's exit deadlines.
        """
        client, websocket = make_client([
            FakeWebSocketStep(message='42["pre_game_start"]'),
            FakeWebSocketStep(is_timeout=True, delay_seconds=0.3),
        ])
        client.game_start_update_timeout_seconds = 0.2

        with self.assertRaisesRegex(ValueError, "no game_update after game start"):
            next(client.get_updates())

    def test_queue_idle_timeout_shorter_than_viewer_zombie_timeout(self) -> None:
        """The queue cancel deadline leaves margin before the viewer self-terminates."""
        self.assertEqual(
            generals.QUEUE_IDLE_TIMEOUT_SECONDS,
            generals.VIEWER_ZOMBIE_TIMEOUT_SECONDS - 60.0)
        self.assertLess(
            generals.QUEUE_IDLE_TIMEOUT_SECONDS
            + generals.QUEUE_CANCEL_GAME_START_GRACE_SECONDS,
            generals.VIEWER_ZOMBIE_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
