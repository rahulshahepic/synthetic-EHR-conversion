"""T-116: deterministic core of the Socratic import builder."""
from __future__ import annotations

import json
from pathlib import Path

from bridge.interview import claims as claims_mod
from bridge.interview import coverage as coverage_mod
from bridge.interview import ledger as ledger_mod
from bridge.interview import profiler as profiler_mod


# -- ledger -------------------------------------------------------------------

def test_ledger_append_only_with_stable_ids(tmp_path):
    p = tmp_path / "led.jsonl"
    e1 = ledger_mod.append_event(p, "question", {"text": "pivot?"})
    e2 = ledger_mod.append_event(p, "answer", {"question_id": e1.id, "text": "30"})
    assert (e1.id, e2.id) == ("E000001", "E000002")
    first_line = p.read_text().splitlines()[0]
    ledger_mod.append_event(p, "claim", {"subject": "s", "predicate": "p", "value": 1, "source": "x"})
    assert p.read_text().splitlines()[0] == first_line  # append-only: line 1 untouched
    events = ledger_mod.read_events(p)
    assert [e.id for e in events] == ["E000001", "E000002", "E000003"]
    assert ledger_mod.answers(events)[e1.id].payload["text"] == "30"


# -- claims -------------------------------------------------------------------

def test_claims_dispute_and_resolution():
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim("date:pivot_year", "value", 50, "DATADICT.TXT v4.1", 0.8))
    assert store.resolved_value("date:pivot_year", "value") == 50
    d = store.add(claims_mod.Claim("date:pivot_year", "value", 30, "ledger:E000009 (Marla Denny)"))
    assert d is not None and not d.resolved and d.values == [50, 30]
    assert store.resolved_value("date:pivot_year", "value") is None  # disputed: no usable value
    store.resolve("date:pivot_year", "value", 30, "OBS-0004")
    assert store.resolved_value("date:pivot_year", "value") == 30
    assert "OBS-0004" in (store.provenance("date:pivot_year", "value") or "")


def test_claims_dictionary_ingest_and_ledger_replay():
    store = claims_mod.ClaimStore()
    n = store.ingest_rows([{"subject": "unit:POT", "predicate": "unit", "value": "MG/DL"}],
                          source="DATADICT.TXT v4.1")
    assert n == 1 and store.resolved_value("unit:POT", "unit") == "MG/DL"
    events = [
        ledger_mod.LedgerEvent("E000001", "claim", {"subject": "a", "predicate": "b",
                                                    "value": 1, "source": "dict"}),
        ledger_mod.LedgerEvent("E000002", "claim", {"subject": "a", "predicate": "b",
                                                    "value": 2, "source": "ledger:E000002"}),
        ledger_mod.LedgerEvent("E000003", "resolve", {"subject": "a", "predicate": "b",
                                                      "value": 2, "source": "OBS-0001"}),
    ]
    replayed = claims_mod.ClaimStore.from_ledger(events)
    assert replayed.resolved_value("a", "b") == 2


# -- coverage -----------------------------------------------------------------

def test_coverage_statuses():
    inv = coverage_mod.Inventory(files={"REG.TXT": ["DOB", "NAME"]}, code_sets=["payer"])
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim("file:REG", "layout_binding", "LAYOUTS.DAT v5.0", "estate"))
    store.add(claims_mod.Claim("field:REG.TXT.DOB", "convention", "YYMMDD", "OBS-0001"))
    store.add(claims_mod.Claim("field:REG.TXT.NAME", "convention", "text30", "dict"))
    store.add(claims_mod.Claim("field:REG.TXT.NAME", "convention", "text40", "ledger:E1"))
    items = {i.subject: i for i in coverage_mod.build_checklist(inv, store)}
    assert items["file:REG"].status == "covered"
    assert items["field:REG.TXT.DOB"].status == "covered"
    assert items["field:REG.TXT.NAME"].status == "disputed"
    assert items["identity"].status == "open"
    assert items["codeset:payer"].status == "open"


# -- profiler: CSV --------------------------------------------------------------

def test_profiler_csv_observations(tmp_path):
    (tmp_path / "patients.csv").write_text(
        "MRN,DOB,TEMP\nP1,800415,98.6\nP2,750930,99.1\nP3,,98.4\n")
    report = profiler_mod.profile_export(tmp_path)
    dob = profiler_mod.observation_for(report, "patients.csv", "DOB")
    assert dob is not None
    assert dob["stats"]["shape_rates"]["YYMMDD"] == 1.0
    assert dob["stats"]["blank_rate"] == round(1 / 3, 4)
    temp = profiler_mod.observation_for(report, "patients.csv", "TEMP")
    assert temp["stats"]["numeric_min"] == 98.4 and temp["stats"]["numeric_max"] == 99.1
    # observations only: no conclusion-shaped keys anywhere
    assert "conclusion" not in json.dumps(report).lower()


# -- profiler: fixed width (Delphi) --------------------------------------------

def _delphi_export(tmp_path) -> Path:
    from testbed.delphi import generate
    out = tmp_path / "delphi"
    generate(out, seed=7, patients=12)
    return out


def test_profiler_fixed_width_delphi(tmp_path):
    out = _delphi_export(tmp_path)
    layouts, version = profiler_mod.parse_layouts_dat((out / "LAYOUTS.DAT").read_text())
    assert version == "5.0" and "REG" in layouts
    report = profiler_mod.profile_export(out, layouts)
    assert report["files"]["REG.TXT"]["records"] >= 12
    dob = profiler_mod.observation_for(report, "REG.TXT", "DOB")
    assert dob["stats"]["shape_rates"]["YYMMDD"] > 0.9
    result = profiler_mod.observation_for(report, "LAB.TXT", "RESULT")
    assert result["stats"].get("flag_suffix_rate", 0) > 0  # value+flag strings observed
    yday = profiler_mod.observation_for(report, "LAB.TXT", "YDAY")
    assert yday["stats"]["shape_rates"]["integer"] == 1.0
    # The profiler observes, without judging, that some YDAY values exceed
    # 366 — data no valid day-of-year can take. What that means is a
    # question for the interview, not for the profiler.
    assert yday["stats"]["numeric_max"] > 366
    name = profiler_mod.observation_for(report, "REG.TXT", "NAME")
    assert "full_width_rate" in name["stats"]  # truncation-pile candidate is measured
