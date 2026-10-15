import math, types, sys
from . import Geometry
class _Any(object):
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()
class RhinoMath(object):
    DefaultAngleTolerance = 0.0174
    @staticmethod
    def UnitScale(a, b): return 1.0 / 12.0   # inches -> feet
class UnitSystem(object):
    Inches = "in"; Feet = "ft"
DocObjects = _Any(); Commands = _Any(); Input = _Any(); UI = _Any(); RhinoApp = _Any(); RhinoDoc = _Any()
