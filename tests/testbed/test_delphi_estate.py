"""The Delphi estate: the shipped data dictionary is deliberately fallible, the
truth ledger in the answer key records exactly how, and the analyst profiles
are complete, self-contained, and disagree with each other where it matters."""
import json
import re
from pathlib import Path

import pytest

from testbed.delphi import layouts
from testbed.delphi.dictionary import DISCREPANCIES
from testbed.delphi.generator import PIVOT_YEAR, generate

ANALYSTS_DIR = Path(__file__).resolve().parents[2] / "testbed" / "delphi" / "analysts"
SECTIONS = ("## Role and tenure", "## What they know well", "## What they do not know",
            "## What they believe that is wrong", "## How they answer")


@pytest.fixture(scope="module")
def export(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("delphi-estate")
    generate(out, seed=42, patients=200)
    return out


def documented_fields(datadict: str) -> dict[str, set[str]]:
    """Extract {file stem: {documented field names}} from DATADICT.TXT."""
    out: dict[str, set[str]] = {}
    current = None
    for line in datadict.splitlines():
        m = re.match(r"== FILE: (\w+)", line)
        if m:
            current = m.group(1)
            out[current] = set()
        elif current and re.match(r"^[A-Z][A-Z0-9]{1,7}\s{2,}", line):
            out[current].add(line.split()[0])
    return out


def layout_fields() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for (stem, _rt), fields in layouts.LAYOUTS.items():
        out.setdefault(stem, set()).update(name for name, *_ in fields)
    return out


def test_dictionary_ships_and_is_version_skewed(export):
    text = (export / "DATADICT.TXT").read_text(encoding="latin-1")
    assert "DATA DICTIONARY" in text and "VERSION 4.1" in text
    assert f"VERSION {layouts.LAYOUT_VERSION}" in (export / "LAYOUTS.DAT").read_text()
    assert layouts.LAYOUT_VERSION != "4.1"
    # the dictionary must not hint that it is fallible or point at the ledger
    assert "estate_discrepancies" not in text and "answer_key" not in text


def test_ledger_shape(export):
    ledger = json.loads((export / "answer_key" / "estate_discrepancies.json").read_text())
    assert ledger == DISCREPANCIES, "export ledger must be the recorded truth, verbatim"
    assert len(ledger) >= 8
    ids = [e["id"] for e in ledger]
    assert len(ids) == len(set(ids))
    for e in ledger:
        assert {"id", "artifact", "claim", "truth", "check"} <= e.keys()


def test_ledger_matches_the_dictionary(export):
    text = (export / "DATADICT.TXT").read_text(encoding="latin-1")
    doc = documented_fields(text)
    lay = layout_fields()
    by_id = {e["id"]: e for e in DISCREPANCIES}
    # wrong date-format claim is in the dictionary; the generator's format is YYMMDD
    assert "MMDDYY" in text and "dict_dob_format" in by_id
    # wrong pivot claim is in the dictionary; the generator's pivot is 30
    assert re.search(r"PIVOT\s*\n?YEAR OF 50|PIVOT YEAR OF 50", text) and PIVOT_YEAR == 30
    assert "dict_pivot_year" in by_id
    # wrong potassium unit in the dictionary; LABDICT (the data) says MEQ/L
    assert "MG/DL" in text
    labdict = {layouts.parse_record("LABDICT", ln)["TEST"]: layouts.parse_record("LABDICT", ln)
               for ln in (export / "LABDICT.TXT").read_text(encoding="latin-1").splitlines()}
    assert labdict["POT"]["UNIT"] == "MEQ/L" and "dict_potassium_unit" in by_id
    # stale field: FAX documented, absent from the layouts
    assert "FAX" in doc["REG"] and "FAX" not in lay["REG"] and "dict_stale_field_fax" in by_id
    # undocumented fields: present in layouts and data, absent from the dictionary
    assert "YDAY" not in doc["LAB"] and "YDAY" in lay["LAB"] and "dict_undocumented_yday" in by_id
    assert "ALGY" not in doc["REG"] and "ALGY" in lay["REG"] and "dict_undocumented_allergy_field" in by_id


def test_appt_status_r_occurs_but_is_undocumented(export):
    statuses = {layouts.parse_record("APPT", ln)["STATUS"]
                for ln in (export / "APPT.TXT").read_text(encoding="latin-1").splitlines()}
    assert "R" in statuses
    text = (export / "DATADICT.TXT").read_text(encoding="latin-1")
    appt_section = text.split("== FILE: APPT")[1].split("==")[0]
    assert "R RESCHEDULED" not in appt_section and "R RE-SCHEDULED" not in appt_section


def test_registration_account_claim_is_false(export):
    text = (export / "DATADICT.TXT").read_text(encoding="latin-1")
    assert "ONE ACCOUNT PER PATIENT" in text
    persons = json.loads((export / "answer_key" / "persons.json").read_text())
    assert any(sum(1 for a in accts if a.startswith("R")) >= 2 for accts in persons.values()), \
        "some person must hold two registration accounts, contradicting the dictionary"


def test_analyst_profiles_complete():
    files = sorted(ANALYSTS_DIR.glob("*.md"))
    assert [f.stem for f in files] == ["lab", "pharmacy", "registration", "systems"]
    for f in files:
        text = f.read_text()
        for section in SECTIONS:
            assert section in text, f"{f.name} missing {section!r}"
        assert "planted" not in text.lower() and "answer key" not in text.lower()


def test_analysts_disagree_on_pivot_and_duplicates():
    reg = (ANALYSTS_DIR / "registration.md").read_text()
    sysm = (ANALYSTS_DIR / "systems.md").read_text()
    pha = (ANALYSTS_DIR / "pharmacy.md").read_text()
    lab = (ANALYSTS_DIR / "lab.md").read_text()
    # the pivot: registration's desk experience says the window starts at 1930;
    # the systems analyst (who wrote the dictionary) says 50
    assert "1930" in reg and "pivot year of 50" in sysm.lower()
    # duplicates: registration calls them the same person; pharmacy warns they
    # are often different people and merging is dangerous
    assert "same person" in reg and "different people" in pha
    # the lab account number as identity: lab asserts it, registration does not
    assert "is the patient" in lab
