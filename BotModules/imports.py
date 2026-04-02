"""
BotModules Centralized Imports

This module provides centralized access to all BotModules classes
while handling circular dependencies through lazy imports.
"""

import importlib
import typing
from functools import lru_cache

# Cache for imported modules
_module_cache = {}

def _get_module(module_name: str):
    """Lazy import a module and cache it."""
    if module_name not in _module_cache:
        _module_cache[module_name] = importlib.import_module(f'BotModules.{module_name}')
    return _module_cache[module_name]

# Lazy accessors for each module
def get_BotStateQueries():
    return _get_module('BotStateQueries').BotStateQueries

def get_BotPathingUtils():
    return _get_module('BotPathingUtils').BotPathingUtils

def get_BotRendering():
    return _get_module('BotRendering').BotRendering

def get_BotRepetition():
    return _get_module('BotRepetition').BotRepetition

def get_BotTimings():
    return _get_module('BotTimings').BotTimings

def get_BotComms():
    return _get_module('BotComms').BotComms

def get_BotTargeting():
    return _get_module('BotTargeting').BotTargeting

def get_BotDefense():
    return _get_module('BotDefense').BotDefense

def get_BotGatherOps():
    return _get_module('BotGatherOps').BotGatherOps

def get_BotExpansionOps():
    return _get_module('BotExpansionOps').BotExpansionOps

def get_BotCombatOps():
    return _get_module('BotCombatOps').BotCombatOps

def get_BotCityOps():
    return _get_module('BotCityOps').BotCityOps

def get_BotEventHandlers():
    return _get_module('BotEventHandlers').BotEventHandlers

def get_BotLifecycle():
    return _get_module('BotLifecycle').BotLifecycle

def get_BotSerialization():
    return _get_module('BotSerialization').BotSerialization

# Direct module access for convenience
BotStateQueries = property(lambda self: get_BotStateQueries())
BotPathingUtils = property(lambda self: get_BotPathingUtils())
BotRendering = property(lambda self: get_BotRendering())
BotRepetition = property(lambda self: get_BotRepetition())
BotTimings = property(lambda self: get_BotTimings())
BotComms = property(lambda self: get_BotComms())
BotTargeting = property(lambda self: get_BotTargeting())
BotDefense = property(lambda self: get_BotDefense())
BotGatherOps = property(lambda self: get_BotGatherOps())
BotExpansionOps = property(lambda self: get_BotExpansionOps())
BotCombatOps = property(lambda self: get_BotCombatOps())
BotCityOps = property(lambda self: get_BotCityOps())
BotEventHandlers = property(lambda self: get_BotEventHandlers())
BotLifecycle = property(lambda self: get_BotLifecycle())
BotSerialization = property(lambda self: get_BotSerialization())

class _ModuleProxy:
    """Proxy class to provide direct access to all BotModules."""
    
    def __getattr__(self, name):
        if name.startswith('get_'):
            return globals()[name]
        else:
            # Try to get the module class
            getter_name = f'get_{name}'
            if getter_name in globals():
                return globals()[getter_name]()
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

# Create a single proxy instance
modules = _ModuleProxy()

# Export the proxy for easy use
__all__ = ['modules']
