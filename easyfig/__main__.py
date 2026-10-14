"""
``python -m easyfig`` - run the command line interface.

Running the module with no arguments prints the CLI help rather than opening the
windowed interface, so an accidental ``python -m easyfig`` in a headless job does
not block on a GUI.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
