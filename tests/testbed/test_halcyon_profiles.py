"""Tests for Halcyon source profiles, in particular T-108's Lakeside profile.

The drift story these pin down: the default (Riverbend) profile and the
Lakeside profile emit measurably different distributions of lab units, visit
codes, and sig text for the same seed, while the default profile's output is
byte-identical to what the generator produced before profiles existed.
"""
import hashlib
import json
import re
import sqlite3

import pytest

from testbed.halcyon import vocab as V
from testbed.halcyon.generator import Config, generate
from testbed.halcyon.profiles import PROFILES, get_profile

# Golden digests of default-profile output (seed 7, 120 patients), computed
# from a pristine checkout of the generator BEFORE profiles existed. Any
# refactor that changes default output by one byte breaks these on purpose.
GOLDEN_DB_SHA256 = "b443cc588f9f8ba3741d8e5bf8e6e755fe3cab87bde41691d597645e8fcb08be"
GOLDEN_ADT_SHA256 = "c4c02842a31e09e24cc284a91aab6cdb0daa5debeaabab079061f5d7f763b80e"
GOLDEN_MANIFEST_SHA256 = "1bca83e1ad705dd3919137be29feb2fe2e3b027b5c73853cba6650f1ff305a71"

ABBREV_SIG = re.compile(r"\b(po|bid|tid|qid|qd|qhs|sq|subq)\b|x\d+\s?d(ays?)?\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def default_export(tmp_path_factory):
    out = tmp_path_factory.mktemp("default")
    summary = generate(out, seed=7, patients=120)
    return out, summary


@pytest.fixture(scope="module")
def lakeside_export(tmp_path_factory):
    out = tmp_path_factory.mktemp("lakeside")
    summary = generate(out, seed=7, patients=120, profile="lakeside")
    return out, summary


def _digest(path):
    con = sqlite3.connect(path)
    h = hashlib.sha256()
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        for row in con.execute(f"SELECT * FROM {t} ORDER BY 1"):
            h.update(repr(row).encode())
    con.close()
    return h.hexdigest()


def _rows(out, sql):
    con = sqlite3.connect(out / "halcyon.db")
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _leading_number(text):
    return float(re.match(r"[\d.]+", text).group())


def test_default_output_matches_pre_profile_golden(default_export):
    out, _ = default_export
    assert _digest(out / "halcyon.db") == GOLDEN_DB_SHA256
    assert hashlib.sha256((out / "feeds/adt_0001.hl7").read_bytes()).hexdigest() == GOLDEN_ADT_SHA256
    assert hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest() == GOLDEN_MANIFEST_SHA256


def test_default_profile_wraps_vocab():
    p = get_profile("default")
    assert p.facilities == tuple(V.FACILITIES)
    assert p.depts == tuple(V.DEPTS)
    assert p.visit_types == V.VISIT_TYPES
    assert set(PROFILES) == {"default", "lakeside"}


def test_profile_selection_and_rates():
    assert Config().profile == "default"
    assert Config().rates["visit_xx"] == 0.01
    assert Config(profile="lakeside").rates["visit_xx"] == 0.03
    with pytest.raises(ValueError):
        Config(profile="bogus")


def test_lakeside_generates(lakeside_export):
    out, summary = lakeside_export
    for p in ["halcyon.db", "manifest.json", "feeds/adt_0001.hl7", "feeds/oru_0001.hl7",
              "feeds/siu_0001.hl7", "extracts/immunizations.csv", "answer_key/issues.jsonl"]:
        assert (out / p).exists(), p
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["profile"] == "lakeside"
    assert "kg" in manifest["notes"]["units"]
    assert {r[0] for r in _rows(out, "SELECT FAC_ID FROM FACILITY")} == {"FAC8", "FAC9"}
    assert {r[0] for r in _rows(out, "SELECT DISTINCT FAC_ID FROM PAT")} == {"FAC8", "FAC9"}
    # the planted-issue machinery still fires under the profile
    assert summary["issues"]["unknown_visit_type"] > 0
    assert summary["issues"]["shared_department"] > 0
    # feeds carry the Lakeside sender, not Riverbend
    assert b"|LAKESIDE|" in (out / "feeds/adt_0001.hl7").read_bytes()


def test_lakeside_lab_units_are_metric(lakeside_export, default_export):
    lake, _ = lakeside_export
    dflt, _ = default_export
    for code, unit in [("GLU", "MMOL/L"), ("CREAT", "UMOL/L"), ("CHOL", "MMOL/L"), ("HGB", "G/L"), ("WBC", "10*9/L")]:
        units = {r[0].upper() for r in _rows(lake, f"SELECT DISTINCT UNITS FROM LAB_RESULT WHERE TEST_CODE='{code}'")}
        assert units == {unit}, (code, units)
    # reference ranges are restated in the metric scale, not just relabeled
    assert {r[0] for r in _rows(lake, "SELECT DISTINCT REF_RANGE FROM LAB_RESULT WHERE TEST_CODE='GLU'")} == {"3.9-5.5"}
    assert {r[0] for r in _rows(lake, "SELECT DISTINCT REF_RANGE FROM LAB_RESULT WHERE TEST_CODE='CREAT'")} == {"53-106"}
    # ...where the default export is unambiguously US-convention
    assert {r[0].upper() for r in _rows(dflt, "SELECT DISTINCT UNITS FROM LAB_RESULT WHERE TEST_CODE='GLU'")} == {"MG/DL"}
    assert {r[0] for r in _rows(dflt, "SELECT DISTINCT REF_RANGE FROM LAB_RESULT WHERE TEST_CODE='GLU'")} == {"70-99"}
    # electrolytes never come out as MEQ/L from Lakeside
    assert not _rows(lake, "SELECT 1 FROM LAB_RESULT WHERE UPPER(UNITS)='MEQ/L' LIMIT 1")


def test_lakeside_vitals_are_metric_scale(lakeside_export, default_export):
    lake, _ = lakeside_export
    dflt, _ = default_export

    def mean(out, col):
        vals = [_leading_number(r[0]) for r in _rows(out, f"SELECT {col} FROM VITALS WHERE {col} != '' LIMIT 4000")]
        return sum(vals) / len(vals)

    # same bodies, different charting: kg weighs ~half of lb, degC ~a third of degF
    assert mean(lake, "WT") < 0.7 * mean(dflt, "WT")
    assert mean(lake, "TEMP") < 60 < mean(dflt, "TEMP")


def test_lakeside_visit_codes_differ(lakeside_export, default_export):
    lake, _ = lakeside_export
    dflt, _ = default_export
    lake_codes = {r[0] for r in _rows(lake, "SELECT DISTINCT VISIT_TYPE FROM VISIT")}
    dflt_codes = {r[0] for r in _rows(dflt, "SELECT DISTINCT VISIT_TYPE FROM VISIT")}
    assert lake_codes <= set(get_profile("lakeside").visit_types)
    assert dflt_codes <= set(V.VISIT_TYPES)
    assert lake_codes.isdisjoint(dflt_codes)
    assert "EST" in lake_codes and "UNK" in lake_codes
    assert "OV" in dflt_codes and "XX" in dflt_codes
    # visits and appointments only reference departments the profile defines
    dept_ids = {r[0] for r in _rows(lake, "SELECT DEPT_ID FROM DEPT")}
    assert {r[0] for r in _rows(lake, "SELECT DISTINCT DEPT_ID FROM VISIT")} <= dept_ids
    assert {r[0] for r in _rows(lake, "SELECT DISTINCT DEPT_ID FROM SCHED")} <= dept_ids


def test_lakeside_sig_style_differs(lakeside_export, default_export):
    lake, _ = lakeside_export
    dflt, _ = default_export
    lake_sigs = {r[0] for r in _rows(lake, "SELECT DISTINCT SIG FROM MED_ORD")}
    dflt_sigs = {r[0] for r in _rows(dflt, "SELECT DISTINCT SIG FROM MED_ORD")}
    pool = {s for sigs in get_profile("lakeside").sig_variants.values() for s in sigs}
    assert lake_sigs <= pool
    # full sentences only: no Latin abbreviations, no "x10d" durations
    assert not [s for s in lake_sigs if ABBREV_SIG.search(s)]
    assert sum("by mouth" in s or "as needed" in s for s in lake_sigs) >= 5
    # the default pool really is abbreviation-heavy, so the shift is real
    assert [s for s in dflt_sigs if ABBREV_SIG.search(s)]


def test_lakeside_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, seed=11, patients=40, profile="lakeside")
    generate(b, seed=11, patients=40, profile="lakeside")
    assert _digest(a / "halcyon.db") == _digest(b / "halcyon.db")
    assert (a / "feeds/oru_0001.hl7").read_bytes() == (b / "feeds/oru_0001.hl7").read_bytes()
