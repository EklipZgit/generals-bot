import importlib
import pathlib
import subprocess
import sys
import typing


_MODULE_NAME = 'maxflow'
_SUBMODULE_DIR = pathlib.Path(__file__).resolve().parent / 'third_party' / 'PyMaxflow'
_STALE_ARTIFACT_GLOB = '_maxflow*.pyd'


def _import_local_pymaxflow():
    module_dir = str(_SUBMODULE_DIR)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    return importlib.import_module(_MODULE_NAME)


def _clear_local_pymaxflow_modules():
    stale_module_names = [name for name in sys.modules.keys() if name == _MODULE_NAME or name.startswith(f'{_MODULE_NAME}.')]
    for stale_module_name in stale_module_names:
        sys.modules.pop(stale_module_name, None)


def _build_local_pymaxflow_inplace():
    subprocess.run(
        [sys.executable, 'setup.py', 'build_ext', '--inplace', '--verbose'],
        cwd=_SUBMODULE_DIR,
        check=True,
    )


try:
    maxflow = _import_local_pymaxflow()
except (ModuleNotFoundError, ImportError):
    try:
        _clear_local_pymaxflow_modules()
        _build_local_pymaxflow_inplace()
        importlib.invalidate_caches()
        _clear_local_pymaxflow_modules()
        maxflow = _import_local_pymaxflow()
    except Exception as build_ex:
        stale_artifacts = sorted(path.name for path in (_SUBMODULE_DIR / 'maxflow').glob(_STALE_ARTIFACT_GLOB))
        stale_artifacts_msg = ''
        if stale_artifacts:
            stale_artifacts_msg = f" Found existing compiled artifacts: {', '.join(stale_artifacts)}."
        raise ImportError(
            f"Could not import local PyMaxflow package '{_MODULE_NAME}'. "
            f"Attempted to build it in-place with `{sys.executable} setup.py build_ext --inplace` in `{_SUBMODULE_DIR}`, "
            f"but that did not produce an importable module.{stale_artifacts_msg}"
        ) from build_ex


Graph = maxflow.Graph
GraphInt = maxflow.GraphInt
GraphFloat = maxflow.GraphFloat


def __getattr__(name: str) -> typing.Any:
    return getattr(maxflow, name)
