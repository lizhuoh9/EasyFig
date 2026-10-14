"""
EasyFig entry point kept at the repository root.

Both invocation styles keep working::

    python main.py                                    # open the GUI
    python main.py plot --table data.csv -o out.png   # render from the CLI
    easyfig plot --table data.csv -o out.png          # installed console script

Anything that is not a known subcommand falls through to the CLI, so its parser
reports the problem.
"""

from __future__ import annotations

import sys

CLI_SUBCOMMANDS = ("plot", "spec", "compose", "layouts", "options", "palettes",
                   "bridge", "gui")


def run_gui():
    """Start the Tk application."""
    import tkinter as tk

    from easyfig.application import DataAnalysisGUI

    root = tk.Tk()
    DataAnalysisGUI(root)
    root.mainloop()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "--gui":
        run_gui()
        return 0
    if argv and argv[0] in ("-h", "--help"):
        from easyfig.cli import build_parser

        build_parser().print_help()
        return 0
    if argv and argv[0] in CLI_SUBCOMMANDS:
        from easyfig.cli import main as cli_main

        return cli_main(argv)
    if argv:
        # Unknown arguments are handed to the CLI so its parser reports them.
        from easyfig.cli import main as cli_main

        return cli_main(argv)

    run_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
