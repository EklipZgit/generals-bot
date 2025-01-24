import pathlib

import logbook
import logging
import os


# logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
FILE_FORMATTER = logging.Formatter("%(asctime)s  %(name)s  %(message)s")
LOG_FORMATTER = logging.Formatter("%(message)s")

LOGGING_SET_UP = False
LOGGING_PORT = 0
LOGGING_QUEUE = None


def add_file_log_output(botName: str, gameMode: str, replayId: str, logFolder: str | None = None):
    # if logFolder is None:
    #     logFolder = "D://GeneralsLogs"
    # fileName = f'{botName}-{gameMode}-{replayId}.txt'
    # fileHandler = logging.FileHandler("{0}/__{1}".format(logFolder, fileName))
    # fileHandler.setFormatter(FILE_FORMATTER)
    # rootLogger = logging.getLogger()
    # rootLogger.addHandler(fileHandler)
    pass


def run_log_output_process(queue, level):
    set_up_logger(level, mainProcess=True, queue=queue)


def set_up_logger(logLevel: int, mainProcess: bool = False, queue = None):
    global LOGGING_SET_UP
    global LOGGING_QUEUE
    # global LOGGING_PORT
    #
    # if port != 0:
    #     LOGGING_PORT = port

    if queue is not None:
        LOGGING_QUEUE = queue
    elif LOGGING_QUEUE is None:
        import multiprocessing
        LOGGING_QUEUE = multiprocessing.Queue(-1)

    if mainProcess:
        import sys
        from logbook import StreamHandler
        my_handler = StreamHandler(sys.stderr, logLevel)  #  format_string=LOG_FORMATTER
        # from logbook.queues import ZeroMQSubscriber
        # subscriber = ZeroMQSubscriber(f'tcp://127.0.0.1:{LOGGING_PORT}')
        # # with my_handler:
        # #     subscriber.dispatch_forever()
        # subscriber.dispatch_in_background(my_handler)
        from logbook.queues import MultiProcessingSubscriber
        subscriber = MultiProcessingSubscriber(LOGGING_QUEUE)
        # subscriber.dispatch_in_background(my_handler)
        with my_handler:
            subscriber.dispatch_forever()

    # if LOGGING_SET_UP:
    #     logbook.info('logging already set up')
    #     return

    LOGGING_SET_UP = True

    if not mainProcess:
        # from logbook.queues import ZeroMQHandler
        # handler = ZeroMQHandler(f'tcp://127.0.0.1:{LOGGING_PORT}', multi=True)
        # handler.push_application()
        from logbook.queues import MultiProcessingHandler
        handler = MultiProcessingHandler(LOGGING_QUEUE)
        handler.push_application()

        logbook.info('yo, first log')

        # # logging.basicConfig(format='%(message)s', level=logbook.debug, force=True)
        # # logging.basicConfig(format='%(levelname)s:%(message)s', filename="D://GeneralsLogs//test.txt", level=logbook.debug, force=True)
        # rootLogger = logging.getLogger()
        # rootLogger.setLevel(logLevel)
        #
        # consoleHandler = logging.StreamHandler()
        # consoleHandler.setFormatter(LOG_FORMATTER)
        # rootLogger.addHandler(consoleHandler)
        #
        # logging.info('got past logbook log...?')


def get_file_safe_username(botName: str) -> str:
    fileSafeUserName = botName.replace("[Bot] ", "")
    fileSafeUserName = fileSafeUserName.replace("[Bot]", "")
    return fileSafeUserName


def get_config_log_folder():
    cfgPath = pathlib.Path(__file__).parent / "../run_config.txt"
    with open(cfgPath, 'r') as file:
        data = file.read()
    cfgContents = data.splitlines()
    for line in cfgContents:
        if "=" not in line:
            continue

        key, value = line.split('=')

        if key == "log_folder":
            return value.strip('/')

    raise AssertionError(f'Unable to find a log folder in {cfgPath}')


def get_file_logging_directory(rawBotName: str, replayId: str) -> str:
    """
    Gets the file logging directory to use for a given bot name and replay id. Makes sure the directory exists.
    @param rawBotName:
    @param replayId:
    @return:
    """
    fileSafeUserName = get_file_safe_username(rawBotName)
    fileSafeUserName = fileSafeUserName.replace("[Bot] ", "")
    fileSafeUserName = fileSafeUserName.replace("[Bot]", "")
    # logbook.info("\n\n\nFILE SAFE USERNAME\n {}\n\n".format(fileSafeUserName))
    logFolder = get_config_log_folder()
    logDirectory = f"{logFolder}//{fileSafeUserName}-{replayId}"

    if not os.path.exists(logDirectory):
        try:
            os.makedirs(logDirectory)
        except:
            logbook.info("Couldn't create dir")

    return logDirectory
