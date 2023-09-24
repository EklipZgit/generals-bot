import sys

IS_DEBUGGING: bool = sys.gettrace() is not None
"""This will be true when a debugger is attached, false otherwise."""