import importlib

_EXPORTS = {
    'BotStateQueries': 'BotStateQueries',
    'BotPathingUtils': 'BotPathingUtils',
    'BotRendering': 'BotRendering',
    'BotRepetition': 'BotRepetition',
    'BotTimings': 'BotTimings',
    'BotComms': 'BotComms',
    'BotTargeting': 'BotTargeting',
    'BotDefense': 'BotDefense',
    'BotDefenseQueries': 'BotDefenseQueries',
    'BotGatherOps': 'BotGatherOps',
    'BotExpansionOps': 'BotExpansionOps',
    'BotExpansionQueries': 'BotExpansionQueries',
    'BotExplorationOps': 'BotExplorationOps',
    'BotCombatOps': 'BotCombatOps',
    'BotCombatQueries': 'BotCombatQueries',
    'BotCityOps': 'BotCityOps',
    'BotCityCaptureControl': 'BotCityCaptureControl',
    'BotEventHandlers': 'BotEventHandlers',
    'BotLifecycle': 'BotLifecycle',
    'BotSerialization': 'BotSerialization',
}


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    module = importlib.import_module(f'.{module_name}', __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS.keys())
