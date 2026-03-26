import sys

IS_DEBUGGING: bool = sys.gettrace() is not None
"""This will be true when a debugger is attached, false otherwise."""

IS_RUNNING_UNIT_TESTS: bool = 'unittest' in sys.modules
IS_DEBUG_OR_UNIT_TEST_MODE: bool = IS_DEBUGGING or IS_RUNNING_UNIT_TESTS


def is_debug_or_unit_test_mode() -> bool:
    return IS_DEBUG_OR_UNIT_TEST_MODE


def log_in_debug_or_unit_tests(message: str, log_func=None):
    if IS_DEBUG_OR_UNIT_TEST_MODE:
        if log_func is None:
            import logbook
            log_func = logbook.info
        log_func(message)