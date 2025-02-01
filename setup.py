# Available at setup time due to pyproject.toml
from pybind11.setup_helpers import Pybind11Extension, build_ext
from Cython.Build import cythonize
from setuptools import setup, Extension
import pathlib

__version__ = "0.0.1"


# ext_modules = [
#     Pybind11Extension(
#         "Knap",
#         ["cpp/KnapsackUtilsCpp.cpp"],
#         # Example: passing in the version to the compiled code
#         define_macros=[("VERSION_INFO", __version__)],
#     ),
# ]


cython_extensions = [
    Extension(str(file).removesuffix(".pyx"), [file],
        extra_compile_args=["-ggdb3"]
    )
    for file in pathlib.Path('.').glob('*pyx')
]

setup(
    name="CythonModules",
    ext_modules=cythonize(cython_extensions, compiler_directives={'language_level': 3},
                           language="c++"),
)

pybind11_extensions = [
    Pybind11Extension(str(file).removesuffix(".cpp"), [file],
        extra_compile_args=["-ggdb3"]
    )
    for file in pathlib.Path('.').glob('*.cpp')
    if '.rendered' not in str(file)
]

setup(
    name="PyBind11Modules",
    ext_modules=pybind11_extensions,
)