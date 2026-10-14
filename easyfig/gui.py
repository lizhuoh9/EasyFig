"""
Windowed launcher for the EasyFig graphical interface.

Installed as the ``easyfig-gui`` command by :pep:`621` ``gui-scripts``, so it
starts without a console window on Windows.  ``easyfig gui`` and
``python main.py`` do the same thing and keep the console attached.
"""

from __future__ import annotations

import sys


def main(argv=None):
    """Open the Tk interface; returns a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        import tkinter as tk
    except ImportError as exc:  # pragma: no cover - depends on the interpreter
        message = (f"EasyFig needs tkinter for the graphical interface: {exc}\n"
                   "Use the command line interface instead, e.g. "
                   "`easyfig plot --help`.")
        print(message, file=sys.stderr)
        return 1

    from .application import DataAnalysisGUI

    root = tk.Tk()
    DataAnalysisGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
