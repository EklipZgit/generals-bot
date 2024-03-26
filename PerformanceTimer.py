from __future__ import annotations

import logbook
import queue
import time
import typing


NS_CONVERTER = (10 ** 9)


class MoveEvent(object):
    def __init__(self, event_name: str, parent: MoveEvent | None):
        self.event_name: str = event_name
        self.event_start_time: float = time.perf_counter()
        self.event_end_time: float | None = None
        self.parent: MoveEvent | None = parent

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.event_end_time = time.perf_counter()
        logbook.info(f'--------------------\n      Complete: ({self.event_end_time - self.event_start_time:.4f}) {self.event_name}\n^^^--------------^^^')

    def get_duration(self):
        endTime = self.event_end_time
        if endTime is None:
            endTime = time.perf_counter()
        return endTime - self.event_start_time


class MoveTimer(object):
    def __init__(self, turn: int):
        self.turn: int = turn
        self.move_beginning_time: float = time.perf_counter()
        self.event_list: typing.List[MoveEvent] = []
        self.move_sent_time: float | None = None
        self._event_stack: "queue.LifoQueue[MoveEvent | None]" = queue.LifoQueue()
        self._event_stack.put(None)

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.move_sent_time = time.perf_counter()
        logbook.info(f'\nMOVE Complete: {self.turn} ({self.move_sent_time - self.move_beginning_time:.4f} in, at game {self.move_sent_time:.4f})\n^^^~~~~~~~~~~~~~~^^^')

    def begin_event(self, event_description: str) -> MoveEvent:
        parent: MoveEvent | None = None

        while self._event_stack.not_empty:
            parent = self._event_stack.get()
            if parent is None or parent.event_end_time is None:
                self._event_stack.put(parent)
                break

        event = MoveEvent(event_description, parent)
        self.event_list.append(event)
        self._event_stack.put(event)
        logbook.info(f'\nvvv--------------vvv\nBeginning: {event_description} ({event.event_start_time - self.move_beginning_time:.4f} in)')
        return event

    def get_events_organized_longest_to_shortest(self, limit: int = 15, indentSize: int = 3) -> typing.List[str]:
        largestN = list(sorted(self.event_list, key=lambda e: e.get_duration(), reverse=True))[0:limit]

        byParent: typing.Dict[str, typing.List[MoveEvent]] = {}

        for event in largestN:
            parentName = ''
            if event.parent is not None:
                parentName = event.parent.event_name

            underParent = byParent.get(parentName, None)
            if underParent is None:
                underParent = []
                byParent[parentName] = underParent

            underParent.append(event)

        # these are now grouped in longest to shortest order, under their parent move events.

        output = self._dump_events_recurse(parentEventName='', eventLookupByParent=byParent, curIndentation='', indentSize=indentSize)
        return output

    def _dump_events_recurse(
            self,
            parentEventName: str,
            eventLookupByParent: typing.Dict[str, typing.List[MoveEvent]],
            curIndentation: str,
            indentSize: int
    ) -> typing.List[str]:
        output = []
        if parentEventName not in eventLookupByParent:
            return output

        nextIndentation = curIndentation + (' ' * indentSize)

        for event in eventLookupByParent[parentEventName]:
            dur = f'{event.get_duration():.4f}'.lstrip('0')
            output.append(f'{curIndentation}{dur} {event.event_name}')
            output.extend(self._dump_events_recurse(event.event_name, eventLookupByParent, nextIndentation, indentSize))

        return output


class PerformanceTimer(object):
    def __init__(self):
        self.move_history: typing.List[MoveTimer] = []
        self.update_received_history: typing.List[float] = []
        self.current_move: MoveTimer | None = None
        self.last_turn = 0
        self.last_update_received_time: float = time.perf_counter()

        self.last_move_sent_time: float = time.perf_counter()

    def record_update(self, turn: int, timeOfUpdate: float):
        """timeOfUpdate needs to be  time.time_ns() / NS_CONVERTER  NOT  time.perf_counter()"""
        if self.current_move is not None:
            if turn != self.current_move.turn + 1:
                logbook.info(f'UPDATE FOR {turn} RECEIVED BEFORE PREVIOUS MOVE {self.current_move.turn} WAS COMPLETE')
            if self.current_move.move_sent_time is None:
                logbook.info(f'UPDATE FOR {turn} RECEIVED while previous move {self.current_move.turn} is still incomplete...? Previous move timer data:')
                logbook.info(str(self.current_move))

        while len(self.update_received_history) <= turn:
            self.update_received_history.append(0.0)

        diff = (time.time_ns() / NS_CONVERTER) - timeOfUpdate
        perfCounterUpdate = time.perf_counter() - diff
        self.last_update_received_time = perfCounterUpdate

        self.update_received_history[turn] = perfCounterUpdate

    def begin_move(self, turn: int) -> MoveTimer:
        newMove = MoveTimer(turn)
        sinceLast = 0.0
        if self.current_move is not None:
            if newMove.turn != self.current_move.turn + 1:
                logbook.info(f'DROPPED MOVE FROM {self.current_move.turn} to {newMove.turn}')
            if self.current_move.move_sent_time is None:
                logbook.info(f'STARTING MOVE {turn} while previous move {self.current_move.turn} is still incomplete...? Previous move timer data:')
                logbook.info(str(self.current_move))
            sinceLast = newMove.move_beginning_time - self.current_move.move_beginning_time
        logbook.info(f'vvv~~~~~~~~~~~~~~vvv\nMOVE Beginning: {turn} ({sinceLast:.4f} since last, at game {newMove.move_beginning_time:.4f})\n~~~~~~~~~~~~~~~~~~~~')
        self.move_history.append(self.current_move)
        self.current_move = newMove
        self.last_turn = turn
        with self.begin_move_event('UPDATE - MOVE START GAP') as moveEvent:
            moveEvent.event_start_time = self.last_update_received_time + 0.000001
        return self.current_move

    def begin_move_event(self, event_description: str) -> MoveEvent:
        """
        Prefer calling move.begin_event directly on the move object returned from begin_move
        @param event_description:
        @return:
        """
        return self.current_move.begin_event(event_description)

    def get_elapsed_since_update(self, turn: int) -> float:
        if turn < len(self.update_received_history):
            elapsed = time.perf_counter() - self.update_received_history[turn]
            return elapsed

        return 0.0