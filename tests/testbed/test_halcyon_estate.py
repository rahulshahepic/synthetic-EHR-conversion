"""T-120: the Halcyon estate — documents, analysts, grading ledger."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ESTATE = ROOT / "testbed/halcyon/estate"
GRADING = ROOT / "testbed/halcyon/grading"
ANALYSTS = ROOT / "testbed/halcyon/analysts"
SECTIONS = ("## Role and tenure", "## What I know", "## What I do not know",
            "## How I answer")


def test_estate_documents_exist():
    assert (ESTATE / "dictionary_excerpts.md").exists()
    assert (ESTATE / "interface_notes.md").exists()
    assert (ESTATE / "README.md").exists()


def test_analyst_profiles_complete():
    files = sorted(ANALYSTS.glob("*.md"))
    assert [f.stem for f in files] == ["him", "interface", "lab", "pharmacy"]
    for f in files:
        text = f.read_text()
        for section in SECTIONS:
            assert section in text, f"{f.name} missing {section!r}"
        assert "planted" not in text.lower() and "answer key" not in text.lower()
        assert "believe that is wrong" not in text


def test_analysts_disagree():
    him = (ANALYSTS / "him.md").read_text()
    iface = (ANALYSTS / "interface.md").read_text()
    lab = (ANALYSTS / "lab.md").read_text()
    # FAC3 timezone: HIM says all Central; the interface engineer says Denver
    assert "Central" in him and "America/Denver" in iface
    # lab completeness: HIM says the extract is complete; the lab says recent
    # results are feed-only
    assert "complete lab record" in him and "feed only" in lab


def test_grading_ledger_shape():
    # The grading ledger lives outside the estate (testbed/halcyon/grading/)
    # so no estate root can serve it; see the firewall acceptance tests.
    assert not (ESTATE / "estate_discrepancies.json").exists()
    ledger = json.loads((GRADING / "estate_discrepancies.json").read_text())
    ids = [e["id"] for e in ledger]
    assert len(ids) == len(set(ids)) and len(ids) >= 6
    for e in ledger:
        assert {"id", "artifact", "claim", "truth", "check"} <= e.keys()
    for expected in ("estate_fac3_timezone", "estate_vital_units_uniform",
                     "estate_charge_cents_always", "estate_lab_extract_complete",
                     "disagreement_fac3_timezone", "disagreement_charge_cents"):
        assert expected in ids, expected
