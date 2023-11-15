from __future__ import annotations

import time
import typing


NS_CONVERTER = (10 ** 9)

NO_ENTRY = (0, 0.0)


class PerfScope(object):
    def __init__(self, event_name: str, telemetry: PerformanceTelemetry):
        self.event_name = event_name
        self.event_start_time: float = time.time_ns() / NS_CONVERTER
        self.event_end_time: typing.Union[None, float] = None
        self.parent: PerformanceTelemetry = telemetry

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.parent.increment_key(self.event_name, time.time_ns() / NS_CONVERTER - self.event_start_time)


class PerformanceTelemetry(object):
    def __init__(self):
        self.key_data: typing.Dict[str, typing.Tuple[int, float]] = {}

    def monitor_telemetry(self, event_description: str) -> PerfScope:
        """
        @param event_description:
        @return:
        """

        return PerfScope(event_description, self)

    def increment_key(self, event_description: str, duration: float):
        curCount, curSumDuration = self.key_data.get(event_description, NO_ENTRY)
        self.key_data[event_description] = (curCount + 1, curSumDuration + duration)

    def get_data_sorted(self) -> typing.List[typing.Tuple[str, int, float]]:
        data = []

        def sorter(eventPlusTuple) -> float:
            eventName, countTimeTuple = eventPlusTuple
            count, totalTime = countTimeTuple
            return totalTime

        for event, countTimeTuple in sorted(self.key_data.items(), key=sorter, reverse=True):
            count, totalTime = countTimeTuple
            data.append((event, count, totalTime))

        return data

    def __str__(self) -> str:
        sorted = self.get_data_sorted()
        return '\n'.join([f'{totalTime:00.4f} {count} - {eventName}' for eventName, count, totalTime in sorted])

