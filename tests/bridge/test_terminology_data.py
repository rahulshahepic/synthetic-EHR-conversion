"""T-105: terminology crosswalk data coverage, schema, and gap-tool logic.

The coverage tests derive every local code list from the source vocabularies
(testbed/halcyon/vocab.py and the Lakeside profile) programmatically, so they
keep passing only while each code either has a crosswalk row or is listed as a
deliberate gap in src/bridge/terminology/data/README.md.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from bridge.terminology import DATA, TERMS
from testbed.halcyon import vocab as V
from testbed.halcyon.profiles.lakeside import LAKESIDE_VISIT_TYPES

NORM = TERMS.norm

# ---------------------------------------------------------------- deliberate gaps (README is the registry)
_GAP_LINE = re.compile(r"^- domain `([^`]+)`, key `([^`]*)`", re.M)


def deliberate_gaps() -> dict[str, set[str]]:
    text = (DATA / "README.md").read_text(encoding="utf-8")
    section = text.split("## Deliberate gaps", 1)[1]
    gaps: dict[str, set[str]] = {}
    for domain, key in _GAP_LINE.findall(section):
        gaps.setdefault(domain, set()).add("" if key == "(blank)" else key)
    return gaps


# ---------------------------------------------------------------- vocab keys vs mapped rows, per domain
def _vocab_keys(domain: str) -> set[str]:
    return {
        "icd9": set(V.ICD9),
        "icd10_retired": set(V.RETIRED_ICD10),
        "local_dx": set(V.LOCAL_DX),
        "formulary": set(V.FORMULARY),
        "allergen": {NORM(k) for k in V.ALLERGENS},
        "reaction": {NORM(k) for k in V.REACTIONS},
        "lab": set(V.LABS),
        "vaccine": set(V.VACCINES),
        "visit_class": set(V.VISIT_TYPES) | set(LAKESIDE_VISIT_TYPES),
        "note_type": set(V.NOTE_TYPES),
        "specialty": {NORM(t) for variants in V.SPECIALTY_TEXT.values() for t in variants},
        "race": {NORM(k) for k in V.RACE_TEXT},
        "free_text_dx": {NORM(t) for t in V.FREE_TEXT_DX},
        "charges": set(V.CHARGES),
    }[domain]


def _mapped(domain: str) -> set[str]:
    return {
        "icd9": set(TERMS.icd9),
        "icd10_retired": set(TERMS.icd10_retired),
        "local_dx": set(TERMS.local_dx),
        "formulary": set(TERMS.formulary),
        "allergen": set(TERMS.allergens),
        "reaction": set(TERMS.reactions),
        "lab": set(TERMS.labs),
        "vaccine": set(TERMS.vaccines),
        "visit_class": set(TERMS.visit_class),
        "note_type": set(TERMS.note_types),
        "specialty": set(TERMS.specialties),
        "race": set(TERMS.race),
        "free_text_dx": set(),  # no crosswalk file exists for free text, by design
        # charge codes map through the source charge master (CPT/HCPCS), not a CSV here
        "charges": {code for code, (_, truth, _) in V.CHARGES.items() if truth},
    }[domain]


DOMAINS = ["icd9", "icd10_retired", "local_dx", "formulary", "allergen", "reaction", "lab",
           "vaccine", "visit_class", "note_type", "specialty", "race", "free_text_dx", "charges"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_vocab_code_maps_or_is_a_documented_gap(domain: str):
    keys, mapped = _vocab_keys(domain), _mapped(domain)
    gaps = deliberate_gaps().get(domain, set())
    assert keys <= mapped | gaps, f"{domain}: neither mapped nor a documented gap: {sorted(keys - mapped - gaps)}"
    assert not (gaps & mapped), f"{domain}: listed as a gap but has a row: {sorted(gaps & mapped)}"
    assert gaps <= keys, f"{domain}: stale gap entries not in the vocabulary: {sorted(gaps - keys)}"


# ---------------------------------------------------------------- rows agree with the vocab truth
def test_mapped_rows_agree_with_vocab_truth():
    for code, (_, truth_targets) in V.ICD9.items():
        if code in TERMS.icd9:
            assert truth_targets[0] in {t[0] for t in TERMS.icd9[code]}, code
    for code, replacements in V.RETIRED_ICD10.items():
        assert set(TERMS.icd10_retired[code]) == set(replacements), code
    for code, (_, truth_icd10) in V.LOCAL_DX.items():
        if code in TERMS.local_dx:
            assert TERMS.local_dx[code][0] == truth_icd10, code
    for code, (_, truth_rx, *_) in V.FORMULARY.items():
        if code in TERMS.formulary:
            assert TERMS.formulary[code][0] == truth_rx, code
    for text, truth in V.ALLERGENS.items():
        if truth is not None and NORM(text) in TERMS.allergens:
            assert TERMS.allergens[NORM(text)][:2] == truth, text
    for text, truth_snomed in V.REACTIONS.items():
        assert TERMS.reactions[NORM(text)][0] == truth_snomed, text
    for code, (_, truth_loinc, *_) in V.LABS.items():
        if code in TERMS.labs:
            assert TERMS.labs[code][0] == truth_loinc, code
    for code, (_, truth_cvx) in V.VACCINES.items():
        if code in TERMS.vaccines:
            assert TERMS.vaccines[code][0] == truth_cvx, code
    for code, (truth_class, _) in V.VISIT_TYPES.items():
        if code in TERMS.visit_class:
            assert TERMS.visit_class[code] == truth_class, code
    for code, (truth_class, _) in LAKESIDE_VISIT_TYPES.items():
        if code in TERMS.visit_class:
            assert TERMS.visit_class[code] == truth_class, code
    for code, (_, truth_loinc) in V.NOTE_TYPES.items():
        assert TERMS.note_types[code][0] == truth_loinc, code
    for truth_specialty, variants in V.SPECIALTY_TEXT.items():
        for text in variants:
            if NORM(text) in TERMS.specialties:
                assert TERMS.specialties[NORM(text)] == truth_specialty, text
    for text, truth in V.RACE_TEXT.items():
        if NORM(text) in TERMS.race:
            assert TERMS.race[NORM(text)] == truth, text


# ---------------------------------------------------------------- CSV file shape
EXPECTED_COLUMNS = {
    "allergen.csv": ["text", "system", "code", "display"],
    "formulary_rxnorm.csv": ["form_code", "rxnorm", "display"],
    "icd10_retired.csv": ["code", "replacement"],
    "icd9_icd10.csv": ["icd9", "icd10", "description"],
    "lab_loinc.csv": ["local_code", "loinc", "ucum_unit", "display"],
    "local_dx.csv": ["local_code", "icd10", "description"],
    "note_type_loinc.csv": ["local_code", "loinc", "display"],
    "race.csv": ["text", "race", "ethnicity"],
    "reaction.csv": ["text", "snomed", "display"],
    "specialty.csv": ["text", "specialty"],
    "vaccine_cvx.csv": ["local_code", "cvx", "display"],
    "visit_class.csv": ["code", "class"],
}
ONE_TO_MANY_FILES = {"icd9_icd10.csv", "icd10_retired.csv"}  # repeated keys are the point there


def _read_csv(name: str) -> list[dict[str, str]]:
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("name,columns", sorted(EXPECTED_COLUMNS.items()))
def test_csv_schema(name: str, columns: list[str]):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == columns
        rows = list(reader)
    assert rows, f"{name} has no data rows"
    for row in rows:
        assert None not in row.values(), f"{name}: short row {row}"
        assert row[columns[0]].strip(), f"{name}: row with an empty key {row}"
    if name not in ONE_TO_MANY_FILES:
        keys = [r[columns[0]] for r in rows]
        assert len(keys) == len(set(keys)), f"{name}: duplicate keys"
    else:
        pairs = [tuple(r[c] for c in columns[:2]) for r in rows]
        assert len(pairs) == len(set(pairs)), f"{name}: duplicate rows"


def test_icd9_one_to_many_rows_exist():
    multi = {code: {t[0] for t in targets} for code, targets in TERMS.icd9.items() if len(targets) > 1}
    assert multi, "expected at least one ICD-9 code mapping to several ICD-10 codes"
    for targets in TERMS.icd9.values():
        for icd10, description in targets:
            assert icd10 and description


def test_synthetic_labeling_present():
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    assert "synthetic" in readme.lower()
    assert "## Deliberate gaps" in readme
    assert set(EXPECTED_COLUMNS) == {p.name for p in DATA.glob("*.csv")}


def test_new_rows_resolve_through_the_loader():
    assert TERMS.icd9["300.00"] == [("F41.9", "Anxiety unspecified")]
    assert TERMS.specialties["misc"] == "other"
    assert {c: TERMS.visit_class[c] for c in ("EST", "NEW", "URG", "DAY", "VID")} == {
        "EST": "ambulatory", "NEW": "ambulatory", "URG": "emergency",
        "DAY": "observation", "VID": "virtual"}
    # and the deliberate gaps really are absent from the crosswalks
    assert "HZ099" not in TERMS.local_dx
    assert "XLAB7" not in TERMS.labs and "PPD" not in TERMS.vaccines
    assert "XX" not in TERMS.visit_class and "UNK" not in TERMS.visit_class
    assert "HFORM0015" not in TERMS.formulary and "HFORM0099" not in TERMS.formulary


# ---------------------------------------------------------------- tools/crosswalk_gaps.py logic
def _load_gap_tool():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "tools" / "crosswalk_gaps.py"
    spec = importlib.util.spec_from_file_location("crosswalk_gaps", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_gaps_classifies_questions():
    tool = _load_gap_tool()
    questions = [
        {"kind": "unmapped_lab", "match_key": "XLAB7", "affected_count": 4},        # gap (deliberate)
        {"kind": "unmapped_lab", "match_key": "GLU", "affected_count": 9},          # has a row: not a gap
        {"kind": "unmapped_medication", "match_key": "HFORM0015", "affected_count": 2},
        {"kind": "unknown_visit_type", "match_key": "EST", "affected_count": 7},     # row added by T-105
        {"kind": "unknown_visit_type", "match_key": "(blank)", "affected_count": 1},  # no key to map
        {"kind": "icd9_one_to_many", "match_key": "493.90", "affected_count": 3},    # caused by rows, not missing ones
        {"kind": "identity_match", "match_key": "A|B", "affected_count": 1},         # not terminology
        {"kind": "unmapped_charge", "match_key": "HC9999", "affected_count": 5},     # charge master, not these CSVs
    ]
    assert tool.find_gaps(questions) == [
        ("unmapped_lab", "XLAB7", 4),
        ("unmapped_medication", "HFORM0015", 2),
    ]
