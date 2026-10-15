"""Imperial length parsing and inch -> model-unit conversion.

Library files store lengths in inches. Any length may be written as a number
(inches) or a string: "5.5", "3-5/8", "3 5/8", "5/8\"", "10'", "1'-6\"", "10' 6 1/2\"".
"""

import re

import Rhino

_FRACTION = re.compile(r"^\s*(?:(\d+(?:\.\d+)?)\s*[- ]\s*)?(\d+)\s*/\s*(\d+)\s*$")


def _parse_inches(s):
    s = s.strip().strip('"').strip()
    if not s:
        return 0.0
    m = _FRACTION.match(s)
    if m:
        whole = float(m.group(1)) if m.group(1) else 0.0
        return whole + float(m.group(2)) / float(m.group(3))
    return float(s)


def parse_length(value):
    """Return a length in inches from a number or an imperial string."""
    if value is None:
        raise ValueError("length is None")
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("″", '"').replace("′", "'")
    s = s.replace("”", '"').replace("’", "'")
    sign = 1.0
    if s.startswith("-"):
        sign, s = -1.0, s[1:]
    if "'" in s:
        feet, rest = s.split("'", 1)
        rest = rest.strip().lstrip("-").strip()
        return sign * (float(feet) * 12.0 + (_parse_inches(rest) if rest else 0.0))
    return sign * _parse_inches(s)


def inch_scale(doc):
    """Multiplier converting inches to the document's model units."""
    return Rhino.RhinoMath.UnitScale(Rhino.UnitSystem.Inches, doc.ModelUnitSystem)


def to_model(doc, value):
    return parse_length(value) * inch_scale(doc)


def to_inches(doc, model_value):
    return model_value / inch_scale(doc)


def format_inches(inches, denominator=16):
    """3.625 -> '3-5/8"', 30.5 -> '2\\'-6 1/2"'."""
    neg = inches < 0
    inches = abs(inches)
    n = int(round(inches * denominator))
    whole, num = divmod(n, denominator)
    den = denominator
    while num and num % 2 == 0:
        num //= 2
        den //= 2
    feet, whole_in = divmod(whole, 12) if whole >= 12 else (0, whole)
    frac = "{}/{}".format(num, den) if num else ""
    if feet:
        inch_part = "{}{}".format(whole_in, " " + frac if frac else "")
        out = "{}'-{}\"".format(feet, inch_part)
    elif whole_in and frac:
        out = '{}-{}"'.format(whole_in, frac)
    elif frac:
        out = '{}"'.format(frac)
    else:
        out = '{}"'.format(whole_in)
    return "-" + out if neg else out
