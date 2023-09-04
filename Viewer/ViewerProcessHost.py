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
from base.client.map import MapBase


class ViewerHost(object):
    def __init__(
            self,
            window_title: str,
            cell_width: int | None = None,
            cell_height: int | None = None,
            alignTop: bool = True,
            alignLeft: bool = True,
            ctx: BaseContext | None = None
    ):
        if ctx is None:
            logging.info("getting spawn context")
            ctx = mp.get_context('spawn')

        self.ctx: BaseContext = ctx
        logging.info("getting mp manager")
        self.mgr: SyncManager = ctx.Manager()
        logging.info("getting mgr queues")
        self._update_queue: "Queue[typing.Tuple[ViewInfo | None, MapBase | None, bool]]" = self.mgr.Queue()
        self._viewer_event_queue: "Queue[bool]" = self.mgr.Queue()
        logging.info("importing GeneralsViewer")
        from base.viewer import GeneralsViewer
        logging.info("newing up GeneralsViewer")
        self._viewer = GeneralsViewer(self._update_queue, self._viewer_event_queue, window_title, cell_width=cell_width, cell_height=cell_height)
        logging.info("newing up viewer process")
        self.process: BaseProcess = self.ctx.Process(target=self._viewer.run_main_viewer_loop, args=(alignTop, alignLeft))


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
        try:
            completedSuccessfully = self._viewer_event_queue.get(block=False)
            if not completedSuccessfully:
                raise AssertionError('pygame viewer indicated it was NOT closed by the user themselves and closed due to failure')
            return True
        except queue.Empty:
            return False
        except BrokenPipeError:
            return True


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