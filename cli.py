#!/usr/bin/env python3
"""
Repository-local launcher for the EasyFig CLI.

The installed entry point is the ``easyfig`` console script (see
``pyproject.toml``); this file exists so ``python cli.py ...`` keeps working from
a checkout without installing anything.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from easyfig.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())