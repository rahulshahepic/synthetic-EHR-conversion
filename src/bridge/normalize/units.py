"""Conservative normalization for synthetic legacy laboratory results.

Unknown units remain unknown; conversions require explicitly supported dimensions.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

ValueKind = Literal["quantity", "coded", "string"]
Comparator = Literal["<", "<=", ">", ">="]


@dataclass(frozen=True)
class ParsedValue:
    kind: ValueKind
    value: float | None
    comparator: Comparator | None
    code: str | None
    text: str


_UNITS: dict[str, str] = {
    "mg/dl": "mg/dL", "mg/dl.": "mg/dL",
    "mmol/l": "mmol/L", "meq/l": "meq/L",
    "g/dl": "g/dL", "g/l": "g/L",
    "mg/l": "mg/L", "ug/ml": "ug/mL", "µg/ml": "ug/mL", "μg/ml": "ug/mL",
    "ng/ml": "ng/mL", "pg/ml": "pg/mL",
    "k/ul": "10*3/uL", "k/µl": "10*3/uL", "k/μl": "10*3/uL",
    "10^3/ul": "10*3/uL", "10*3/ul": "10*3/uL",
    "m/ul": "10*6/uL", "10^6/ul": "10*6/uL", "10*6/ul": "10*6/uL",
    "%": "%", "mmhg": "mm[Hg]", "mm[hg]": "mm[Hg]",
    "f": "[degF]", "°f": "[degF]", "[degf]": "[degF]",
    "c": "Cel", "°c": "Cel", "cel": "Cel",
    "lbs": "[lb_av]", "lb": "[lb_av]", "[lb_av]": "[lb_av]",
    "kg": "kg", "g": "g", "mg": "mg",
    "in": "[in_i]", "inch": "[in_i]", "inches": "[in_i]", "[in_i]": "[in_i]",
    "cm": "cm", "mm": "mm", "m": "m",
    "iu/l": "[IU]/L", "[iu]/l": "[IU]/L",
    "u/l": "U/L", "bpm": "/min", "/min": "/min",
    "ml": "mL", "l": "L", "ul": "uL", "µl": "uL", "μl": "uL",
    "ms": "ms", "s": "s", "ph": "[pH]", "[ph]": "[pH]",
    "umol/l": "umol/L", "µmol/l": "umol/L", "μmol/l": "umol/L", "nmol/l": "nmol/L",
    "10*9/l": "10*9/L", "10^9/l": "10*9/L", "miu/l": "mIU/L", "uiu/ml": "uIU/mL",
}


def normalize_unit(raw: str) -> str | None:
    """Return an explicitly recognized UCUM unit, not an inferred approximation."""
    return _UNITS.get(raw.strip().casefold()) if isinstance(raw, str) else None


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_QUANTITY = re.compile(rf"^\s*(<=|>=|≤|≥|<|>)?\s*({_NUMBER})\s*$")
_CODES = {"POS": "positive", "POSITIVE": "positive",
          "NEG": "negative", "NEGATIVE": "negative",
          "DET": "detected", "DETECTED": "detected",
          "ND": "not-detected", "NOT DETECTED": "not-detected",
          "TRACE": "trace"}


def parse_result_value(raw: str) -> ParsedValue:
    """Preserve original text even for recognized structured results."""
    text = raw.strip()
    match = _QUANTITY.fullmatch(text)
    if match:
        comp = {"≤": "<=", "≥": ">="}.get(match[1], match[1])
        value = float(match[2])
        if math.isfinite(value):
            return ParsedValue("quantity", value, comp, None, text)
    code = _CODES.get(text.upper())
    if code is not None:
        return ParsedValue("coded", None, None, code, text)
    return ParsedValue("string", None, None, None, text)


_RANGE = re.compile(rf"^\s*({_NUMBER})\s*[-–]\s*({_NUMBER})\s*$")


def parse_reference_range(raw: str) -> tuple[float | None, float | None]:
    """Return inclusive numeric bounds; strict inequality is represented by its limit."""
    text = raw.strip()
    between = _RANGE.fullmatch(text)
    if between:
        low, high = float(between[1]), float(between[2])
        if math.isfinite(low) and math.isfinite(high) and low <= high:
            return low, high
        return None, None
    val = parse_result_value(text)
    if val.kind != "quantity" or val.comparator is None:
        return None, None
    if val.comparator in ("<", "<="):
        return None, val.value
    return val.value, None


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert only supported pairs. Raises ValueError for ambiguous units."""
    source, target = normalize_unit(from_unit), normalize_unit(to_unit)
    if source is None or target is None:
        raise ValueError(f"Unknown conversion unit: {from_unit!r} -> {to_unit!r}")
    if not math.isfinite(value):
        raise ValueError("Conversion value must be finite")
    if source == target:
        return float(value)
    factors = {
        ("[lb_av]", "kg"): 0.45359237,
        ("kg", "[lb_av]"): 1 / 0.45359237,
        ("[in_i]", "cm"): 2.54,
        ("cm", "[in_i]"): 1 / 2.54,
        ("mg/dL", "mmol/L"): 1 / 18.0182,
        ("mmol/L", "mg/dL"): 18.0182,
    }
    if source == "[degF]" and target == "Cel":
        return (value - 32) * 5 / 9
    if source == "Cel" and target == "[degF]":
        return value * 9 / 5 + 32
    factor = factors.get((source, target))
    if factor is None:
        raise ValueError(f"Unsupported conversion: {source} -> {target}")
    return value * factor
