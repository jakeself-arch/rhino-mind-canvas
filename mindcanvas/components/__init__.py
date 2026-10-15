"""Auto-registers every component module in this folder."""

import importlib
import os

from .base import REGISTRY, get, register  # noqa: F401

_here = os.path.dirname(os.path.abspath(__file__))
for _name in sorted(os.listdir(_here)):
    if _name.endswith(".py") and not _name.startswith("_") and _name != "base.py":
        importlib.import_module("." + _name[:-3], __name__)
