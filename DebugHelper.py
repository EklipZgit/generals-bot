import sys

def _detect_debugger_attached() -> bool:
    gettrace = getattr(sys, "gettrace", None)
    if callable(gettrace):
        trace = gettrace()
        if trace is not None:
            return True

    frame_getter = getattr(sys, "_getframe", None)
    if callable(frame_getter):
        frame = frame_getter()
        while frame is not None:
            if frame.f_trace is not None:
                return True
            frame = frame.f_back

    pydevd_mod = sys.modules.get("pydevd")
    if pydevd_mod is not None:
        get_global_debugger = getattr(pydevd_mod, "get_global_debugger", None)
        if callable(get_global_debugger):
            try:
                if get_global_debugger() is not None:
                    return True
            except Exception:
                pass

    debugpy_mod = sys.modules.get("debugpy")
    if debugpy_mod is not None:
        is_client_connected = getattr(debugpy_mod, "is_client_connected", None)
        if callable(is_client_connected):
            try:
                if is_client_connected():
                    return True
            except Exception:
                pass

    return False


class _DynamicDebugFlag(object):
    def __bool__(self):
        return _detect_debugger_attached()


def _is_debugging() -> bool:
    return IS_DEBUGGING


class _DynamicDebugOrUnitTestFlag(object):
    def __bool__(self):
        return _is_debugging() or IS_RUNNING_UNIT_TESTS


IS_DEBUGGING = bool(_DynamicDebugFlag())
"""This will be true when a debugger is attached, false otherwise."""

IS_RUNNING_UNIT_TESTS: bool = 'unittest' in sys.modules
IS_DEBUG_OR_UNIT_TEST_MODE = bool(_DynamicDebugOrUnitTestFlag())


def is_debug_or_unit_test_mode() -> bool:
    return IS_DEBUG_OR_UNIT_TEST_MODE