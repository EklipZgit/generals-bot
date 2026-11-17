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
    'BotExplorationOps': 'BotExplorationOps',
    'BotCombatOps': 'BotCombatOps',
    'BotCombatQueries': 'BotCombatQueries',
    'BotCityOps': 'BotCityOps',
    'BotCentralDefense': 'BotCentralDefense',
    'BotCityCaptureControl': 'BotCityCaptureControl',
    'BotEventHandlers': 'BotEventHandlers',
    'BotLifecycle': 'BotLifecycle',
    'BotSerialization': 'BotSerialization',
    'BotKillTiming': 'BotKillTiming',
    'BotFfaEndgame': 'BotFfaEndgame',
    'BotStealthAllIn': 'BotStealthAllIn',
}


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

    # Tests/test_ArmyInterception.py interception call sites use the
    # BM.BotCombatOps.BotCombatOps.kill_threat module.Class.method idiom; returning
    # the class here instead of the module made BM.X.ClassAttribute resolve to
    # class.nonexistent_attribute and raised AttributeError once the class had been
    # cached before the submodule import bound the real module attribute.
    module = importlib.import_module(f'.{module_name}', __name__)
    globals()[name] = module
    return module


__all__ = list(_EXPORTS.keys())
