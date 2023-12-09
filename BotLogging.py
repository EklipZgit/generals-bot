import logging
import os

import logbook

# logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
FILE_FORMATTER = logging.Formatter("%(asctime)s  %(name)s  %(message)s")
LOG_FORMATTER = logging.Formatter("%(message)s")

LOGGING_SET_UP = False


def add_file_log_output(botName: str, gameMode: str, replayId: str, logFolder: str | None = None):
    # if logFolder is None:
    #     logFolder = "D:\\GeneralsLogs"
    # fileName = f'{botName}-{gameMode}-{replayId}.txt'
    # fileHandler = logging.FileHandler("{0}/__{1}".format(logFolder, fileName))
    # fileHandler.setFormatter(FILE_FORMATTER)
    # rootLogger = logging.getLogger()
    # rootLogger.addHandler(fileHandler)
    pass

def set_up_logger(logLevel: int, mainProcess: bool = False):
    global LOGGING_SET_UP

    if LOGGING_SET_UP:
        logging.info('logging already set up')
        return

    LOGGING_SET_UP = True

    if mainProcess:
        from logbook import StreamHandler
        import sys
        my_handler = StreamHandler(sys.stdout, logLevel, format_string=LOG_FORMATTER)
        from logbook.queues import ZeroMQSubscriber
        subscriber = ZeroMQSubscriber('tcp://127.0.0.1:12345')
        with my_handler:
            subscriber.dispatch_forever()

    else:
        from logbook.queues import ZeroMQHandler
        handler = ZeroMQHandler('tcp://127.0.0.1:12345')
        handler.push_application()
    #
    # # logging.basicConfig(format='%(message)s', level=logging.DEBUG, force=True)
    # # logging.basicConfig(format='%(levelname)s:%(message)s', filename="D:\\GeneralsLogs\\test.txt", level=logging.DEBUG, force=True)
    # rootLogger = logging.getLogger()
    # rootLogger.setLevel(logLevel)
    #
    # consoleHandler = logging.StreamHandler()
    # consoleHandler.setFormatter(LOG_FORMATTER)
    # rootLogger.addHandler(consoleHandler)


def get_file_safe_username(botName: str) -> str:
    fileSafeUserName = botName.replace("[Bot] ", "")
    fileSafeUserName = fileSafeUserName.replace("[Bot]", "")
    return fileSafeUserName


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
    # logging.info("\n\n\nFILE SAFE USERNAME\n {}\n\n".format(fileSafeUserName))
    logDirectory = "D:\\GeneralsLogs\\{}-{}".format(fileSafeUserName, replayId)

    if not os.path.exists(logDirectory):
        try:
            os.makedirs(logDirectory)
        except:
            logbook.info("Couldn't create dir")

    return logDirectory