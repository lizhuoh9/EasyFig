"""
EasyFig - turn measurement tables into publication-ready charts.

The package ships two front ends over one rendering engine:

* ``easyfig.application`` - the Tk GUI
* ``easyfig.cli``         - the command line interface (``easyfig`` command)

Both build their figure through :mod:`easyfig.chart_builder`, so a chart rendered
from a terminal is identical to the one shown in the preview window.
"""

from __future__ import annotations

__version__ = "1.3.0"

__all__ = [
    "__version__",
    "chart_builder",
    "chart_manager",
    "data_processor",
    "palettes",
]


def __getattr__(name):
    """Import submodules lazily.

    Importing ``easyfig`` must stay cheap: ``easyfig.palettes`` is usable from a
    minimal environment, and pulling in matplotlib or tkinter should only happen
    when the caller actually asks for a rendering module.
    """
    if name in __all__:
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
