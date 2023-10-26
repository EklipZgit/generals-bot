import logging
import queue
import traceback
import typing
from multiprocessing import Queue
from multiprocessing.context import BaseContext
import multiprocessing as mp
from multiprocessing.managers import SyncManager
from multiprocessing.process import BaseProcess

from ViewInfo import ViewInfo
from base.client.map import MapBase, Tile


class ViewerHost(object):
    def __init__(
            self,
            window_title: str,
            cell_width: int | None = None,
            cell_height: int | None = None,
            alignTop: bool = True,
            alignLeft: bool = True,
            ctx: BaseContext | None = None,
            onClick: typing.Callable[[Tile, bool], None] | None = None,
            noLog: bool = False
    ):
        if ctx is None:
            logging.info("getting spawn context")
            ctx = mp.get_context('spawn')

        self.on_click: typing.Callable[[Tile, bool], None] | None = onClick
        self.ctx: BaseContext = ctx
        logging.info("getting mp manager")
        self.mgr: SyncManager = ctx.Manager()
        logging.info("getting mgr queues")
        self._update_queue: "Queue[typing.Tuple[ViewInfo | None, MapBase | None, bool]]" = self.mgr.Queue()
        self._viewer_event_queue: "Queue[typing.Tuple[str, typing.Any]]" = self.mgr.Queue()
        logging.info("importing GeneralsViewer")
        from base.viewer import GeneralsViewer
        logging.info("newing up GeneralsViewer")
        self._viewer = GeneralsViewer(self._update_queue, self._viewer_event_queue, window_title, cell_width=cell_width, cell_height=cell_height, no_log=noLog)
        self._closed_by_user: bool | None = None
        logging.info("newing up viewer process")
        self.process: BaseProcess = self.ctx.Process(target=self._viewer.run_main_viewer_loop, args=(alignTop, alignLeft))
        self.no_log: bool = noLog

    def __getstate__(self):
        raise AssertionError('this should never get serialized')

    def __setstate__(self, state):
        raise AssertionError('this should never get de-serialized')

    def start(self):
        logging.info("starting viewer process")
        self.process.start()

    def kill(self):
        logging.info("putting Complete viewer update in queue")
        try:
            self._update_queue.put((None, None, True))
        except BrokenPipeError:
            pass

        logging.info("joining viewer")
        if self.process.is_alive():
            self.process.join(1.0)
            logging.info("killing viewer")
            self.process.kill()

    def check_viewer_closed(self) -> bool:
        if self._viewer is None:
            return True

        if self._closed_by_user is not None:
            return True

        # if not self.process.is_alive():
        #     return True

        self.handle_viewer_events()
        if self._closed_by_user is not None:
            # if not closedByUser:
            #     raise AssertionError('pygame viewer indicated it was NOT closed by the user themselves and closed due to failure')
            return True

    def check_viewer_closed_by_user(self) -> bool:
        if self.check_viewer_closed():
            if self._closed_by_user:
                return True

        return False

    def send_update_to_viewer(self, viewInfo: ViewInfo, map: MapBase, isComplete: bool = False):
        try:
            obj = (viewInfo, map, isComplete)
            # import dill
            # try:
            #     print('TESTING MAP')
            #     TestPickle.test_pickle_v2(map)
            #
            #     print('TESTING VIEW INFO')
            #     TestPickle.test_pickle_v2(viewInfo)
            #     # string = dill.dumps(obj)
            #     # logging.info('DILL dumped???')
            #     # logging.info(string)
            #     # logging.info('DILL loading:')
            #     # dill.loads(string)
            # except:
            #     logging.info(f'DILL LOAD ERROR: ' + traceback.format_exc())
            #     pass

            self._update_queue.put(obj)
        except BrokenPipeError as ex:
            if ex.winerror == 232:
                logging.info('multi processing is shutting down, got a BrokenPipeError from the viewer, unable to send (final?) update to viewer.')
            else:
                logging.info(f'outer update publish catch, error: ')
                logging.info(traceback.format_exc())
        except:
            logging.info(f'outer update publish catch, error: ')
            logging.info(traceback.format_exc())

    def handle_viewer_events(self):
        try:
            while True:
                eventType, eventValue = self._viewer_event_queue.get(block=False)
                if eventType == 'CLOSED':
                    closedByUser = eventValue
                    self._closed_by_user = closedByUser

                if self.on_click is not None:
                    if eventType == 'LEFT_CLICK':
                        self.on_click(eventValue, False)
                    elif eventType == 'RIGHT_CLICK':
                        self.on_click(eventValue, True)
        except queue.Empty:
            pass
        except BrokenPipeError:
            if self._closed_by_user is None:
                self._closed_by_user = False