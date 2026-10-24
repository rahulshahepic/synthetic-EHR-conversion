import math
import pytest

from bridge.normalize.units import (
    ParsedValue, convert, normalize_unit, parse_reference_range, parse_result_value,
)


@pytest.mark.parametrize(("raw", "expected"), [
    ("mg/dl", "mg/dL"), ("MG/DL", "mg/dL"), ("MEQ/L", "meq/L"),
    ("K/uL", "10*3/uL"), ("10^3/uL", "10*3/uL"), ("%", "%"),
    ("mmHg", "mm[Hg]"), ("F", "[degF]"), ("°F", "[degF]"),
    ("lbs", "[lb_av]"), ("lb", "[lb_av]"), ("kg", "kg"),
    ("C", "Cel"), ("°C", "Cel"), ("mmol/L", "mmol/L"),
    ("g/dL", "g/dL"), ("µg/mL", "ug/mL"), ("ng/mL", "ng/mL"),
    ("ml", "mL"), ("IU/L", "[IU]/L"), ("  mg/dL  ", "mg/dL"),
    ("", None), ("foobar", None), ("mg/kg/day", None),
])
def test_units(raw, expected):
    assert normalize_unit(raw) == expected


@pytest.mark.parametrize(("raw", "kind", "value", "comparison", "code"), [
    ("12", "quantity", 12, None, None), ("-3.5", "quantity", -3.5, None, None),
    (".25", "quantity", .25, None, None), ("1e3", "quantity", 1000, None, None),
    ("<5", "quantity", 5, "<", None), ("<= 7", "quantity", 7, "<=", None),
    (">2", "quantity", 2, ">", None), (">= 60", "quantity", 60, ">=", None),
    ("≤ 5", "quantity", 5, "<=", None), ("≥2", "quantity", 2, ">=", None),
    ("POS", "coded", None, None, "positive"),
    ("neg", "coded", None, None, "negative"),
    ("DET", "coded", None, None, "detected"),
    ("ND", "coded", None, None, "not-detected"),
    ("TRACE", "coded", None, None, "trace"),
    ("not detected", "coded", None, None, "not-detected"),
    ("hemolyzed", "string", None, None, None),
    ("12 mg/dL", "string", None, None, None),
    ("nan", "string", None, None, None),
    ("1-2", "string", None, None, None),
])
def test_value(raw, kind, value, comparison, code):
    actual = parse_result_value(raw)
    assert actual == ParsedValue(kind, value, comparison, code, raw.strip())


@pytest.mark.parametrize(("raw", "expected"), [
    ("3.5-5.1", (3.5, 5.1)), ("-2--1", (-2, -1)),
    ("<200", (None, 200)), ("<=200", (None, 200)),
    (">=60", (60, None)), (">20", (20, None)),
    ("neg", (None, None)), ("", (None, None)),
    ("5-3", (None, None)), ("a-b", (None, None)),
    ("4–8", (4, 8)),
])
def test_range(raw, expected):
    assert parse_reference_range(raw) == expected


@pytest.mark.parametrize(("value", "source", "target", "expected"), [
    (32, "F", "C", 0), (212, "F", "C", 100),
    (0, "C", "F", 32), (100, "C", "F", 212),
    (1, "lb", "kg", 0.45359237),
    (1, "kg", "lb", 1 / .45359237),
    (1, "in", "cm", 2.54), (2.54, "cm", "in", 1),
    (180.182, "mg/dL", "mmol/L", 10),
    (10, "mmol/L", "mg/dL", 180.182),
    (12, "mg/dL", "mg/dL", 12),
])
def test_convert(value, source, target, expected):
    assert convert(value, source, target) == pytest.approx(expected)


@pytest.mark.parametrize(("value", "source", "target"), [
    (1, "unknown", "kg"), (1, "kg", "mg/dL"),
    (1, "mg/dL", "kg"), (float("nan"), "kg", "kg"),
    (float("inf"), "kg", "lb"),
])
def test_convert_reject(value, source, target):
    with pytest.raises(ValueError):
        convert(value, source, target)
