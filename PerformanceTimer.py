import logging
import time
import typing


class MoveEvent(object):
    def __init__(self, event_name: str):
        self.event_name = event_name
        self.event_start_time: float = time.perf_counter()
        self.event_end_time: typing.Union[None, float] = None

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.event_end_time = time.perf_counter()
        logging.info(f'--------------------\nComplete: {self.event_name} ({self.event_end_time - self.event_start_time:.3f})\n^^^--------------^^^')

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
        self.move_sent_time: typing.Union[None, float] = None

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.move_sent_time = time.perf_counter()
        logging.info(f'~~~~~~~~~~~~~~~~~~~~\nMOVE Complete: {self.turn} ({self.move_sent_time - self.move_beginning_time:.3f} in, at game {self.move_sent_time:.3f})\n^^^~~~~~~~~~~~~~~^^^')

    def begin_event(self, event_description: str) -> MoveEvent:
        event = MoveEvent(event_description)
        self.event_list.append(event)
        logging.info(f'vvv--------------vvv\nBeginning: {event_description} ({event.event_start_time - self.move_beginning_time:.3f} in)\n--------------------')
        return event


class PerformanceTimer(object):
    def __init__(self):
        self.move_history: typing.List[MoveTimer] = []
        self.current_move: MoveTimer = None
        self.last_turn = 0
        self.last_update_received_time: float = time.perf_counter()
        self.last_move_sent_time: float = time.perf_counter()

    def record_update(self, turn: int):
        if self.current_move is not None:
            if turn != self.current_move.turn + 1:
                logging.info(f'UPDATE FOR {turn} RECEIVED BEFORE PREVIOUS MOVE {self.current_move.turn} WAS COMPLETE')
            if self.current_move.move_sent_time is None:
                logging.info(f'UPDATE FOR {turn} RECEIVED while previous move {self.current_move.turn} is still incomplete...? Previous move timer data:')
                logging.info(str(self.current_move))

        self.last_update_received_time = time.perf_counter()

    def begin_move(self, turn: int) -> MoveTimer:
        newMove = MoveTimer(turn)
        sinceLast = 0.0
        if self.current_move is not None:
            if newMove.turn != self.current_move.turn + 1:
                logging.info(f'DROPPED MOVE FROM {self.current_move.turn} to {newMove.turn}')
            if self.current_move.move_sent_time is None:
                logging.info(f'STARTING MOVE {turn} while previous move {self.current_move.turn} is still incomplete...? Previous move timer data:')
                logging.info(str(self.current_move))
            sinceLast = newMove.move_beginning_time - self.current_move.move_beginning_time
        logging.info(f'vvv~~~~~~~~~~~~~~vvv\nMOVE Beginning: {turn} ({sinceLast:.3f} since last, at game {newMove.move_beginning_time:.3f})\n~~~~~~~~~~~~~~~~~~~~')
        self.move_history.append(self.current_move)
        self.current_move = newMove
        self.last_turn = turn
        return self.current_move

    def begin_move_event(self, event_description: str) -> MoveEvent:
        """
        Prefer calling move.begin_event directly on the move object returned from begin_move
        @param event_description:
        @return:
        """
        return self.current_move.begin_event(event_description)

