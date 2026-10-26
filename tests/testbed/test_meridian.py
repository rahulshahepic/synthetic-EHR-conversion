"""Meridian testbed: deterministic export, a fallible estate with its grading ledger, analyst
profiles that disagree, and an end-to-end graded conversion through the generated profile."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from testbed.meridian import estate
from testbed.meridian.generator import FILES, generate

ANALYSTS = Path(__file__).resolve().parents[2] / "testbed" / "meridian" / "analysts"
SECTIONS = ("## Role and tenure", "## What I know", "## What I do not know", "## How I answer")


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(path.glob("*")):
        if f.is_file():
            h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()


def test_generation_is_deterministic(tmp_path):
    generate(tmp_path / "a", seed=7, patients=40)
    generate(tmp_path / "b", seed=7, patients=40)
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")
    assert _digest(tmp_path / "a" / "answer_key") == _digest(tmp_path / "b" / "answer_key")


def test_files_are_pipe_delimited_with_headers_and_counted(tmp_path):
    generate(tmp_path, seed=1, patients=40)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    for stem, header in FILES.items():
        lines = (tmp_path / f"{stem}.DAT").read_bytes().decode("latin-1").split("\r\n")
        assert lines[0] == "|".join(header)
        rows = [ln for ln in lines[1:] if ln]
        assert len(rows) == manifest["counts"][stem]
        assert all(ln.count("|") == len(header) - 1 for ln in rows)
    assert not (tmp_path / "IMMUNE.DAT").exists()  # the guide lists it; the extract never had it


def test_estate_ships_without_leaking_the_grading_ledger(tmp_path):
    generate(tmp_path, seed=1, patients=20)
    for doc in ("MCS2_EXTRACT_GUIDE.TXT", "KICKOFF_MEMO.TXT"):
        text = (tmp_path / doc).read_text(encoding="latin-1")
        assert "answer_key" not in text and "discrepanc" not in text.lower()
    ledger = json.loads((tmp_path / "answer_key" / "estate_discrepancies.json").read_text())
    assert ledger == estate.DISCREPANCIES
    kinds = {e["kind"] for e in ledger}
    assert {"dictionary", "analyst-belief", "analyst-disagreement"} <= kinds


@pytest.mark.parametrize("name", ["registration", "lab", "pharmacy", "interface"])
def test_analyst_profiles_complete(name):
    text = (ANALYSTS / f"{name}.md").read_text()
    for s in SECTIONS:
        assert s in text
    assert "answer key" not in text.lower() and "planted" not in text.lower()


def test_analysts_disagree_on_duplicates_and_sun_ridge_time():
    reg = (ANALYSTS / "registration.md").read_text()
    itf = (ANALYSTS / "interface.md").read_text()
    assert "merged every duplicate" in reg and "still have\n  two registrations" in itf
    assert "everything in MCS/2 is\n  Mountain Time" in reg and "America/Phoenix" in itf


def test_end_to_end_conversion_grades(tmp_path):
    from testbed.meridian.demo import run_demo
    result = run_demo(tmp_path, seed=42, patients=300)
    assert result["status"] == "completed"
    grade = (tmp_path / "GRADE.md").read_text()
    for line in ("| Encounter time zone (SRC) | 332 | 332 | 0 |", "| Cancelled lab results kept out of Nimbus | 69 | 69 | 0 |",
                 "| Medication RxNorm = truth | 355 | 355 | 0 |", "Identity pairwise precision 1.000"):
        assert line in grade
    assert "swallowed" not in grade and "| missed |" not in grade
