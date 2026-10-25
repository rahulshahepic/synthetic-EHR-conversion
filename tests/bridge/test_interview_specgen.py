"""T-118: spec generator (declarative-first) + extract dispatch."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.extract.registry import get_reader, reader_names
from bridge.interview import claims as claims_mod
from bridge.interview import ledger as ledger_mod
from bridge.interview import profiler as profiler_mod
from bridge.interview import reader as reader_mod
from bridge.interview import specgen


def _store() -> claims_mod.ClaimStore:
    store = claims_mod.ClaimStore()
    store.ingest_rows([
        {"subject": "profile", "predicate": "pivot_year", "value": 50},
        {"subject": "unit:POT", "predicate": "unit", "value": "MG/DL"},
    ], source="DATADICT.TXT v4.1")
    store.add(claims_mod.Claim("profile", "pivot_year", 30,
                               "ledger:E000010 (Marla Denny, registration)"))
    store.resolve("profile", "pivot_year", 30, "OBS-0042 (DOB distribution)",
                  evidence_refs=("OBS-0042",))
    return store


def test_spec_is_deterministic_and_declarative_first():
    # The resolution cites OBS-0042: data confirmation requires that the
    # observation actually be recorded in the ledger events (validated
    # provenance — a citation string alone confirms nothing).
    events = [ledger_mod.LedgerEvent("E000001", "claim", {}),
              ledger_mod.LedgerEvent("E000002", "observation",
                                     {"obs_id": "OBS-0042", "file": "REG.TXT",
                                      "field": "DOB",
                                      "stats": {"shape_rates": {"YYMMDD": 1.0}}})]
    a = specgen.generate_spec(events, _store(), "delphi")
    b = specgen.generate_spec(events, _store(), "delphi")
    assert a.spec_json() == b.spec_json()
    assert a.profile_code == b.profile_code
    spec = json.loads(a.spec_json())
    assert spec["source"] == "delphi"
    pivot = next(r for r in spec["rules"] if r["subject"] == "profile" and r["predicate"] == "pivot_year")
    assert pivot["value"] == 30
    assert pivot["provenance"]["kind"] == "analyst"
    assert pivot["data_confirmed"] is True       # resolution cited a profiler observation
    pot = next(r for r in spec["rules"] if r["subject"] == "unit:POT")
    assert pot["provenance"]["kind"] == "dictionary"
    assert pot["data_confirmed"] is False        # dictionary alone never confirms


def test_generated_profile_is_a_thin_rendering():
    pkg = specgen.generate_spec([], _store(), "delphi")
    ns: dict = {}
    exec(pkg.profile_code, ns)
    assert ns["PIVOT_YEAR"] == 30
    assert ns["MERGE_POLICY"] == "route_to_reconciliation"
    assert "# provenance:" in pkg.profile_code


def test_identity_merges_route_to_human_despite_analyst_claim():
    store = _store()
    store.add(claims_mod.Claim("identity", "merge_policy", "auto_merge",
                               "ledger:E000011 (Marla Denny, registration)"))
    store.add(claims_mod.Claim("identity", "keying_story",
                               "Departmental accounts matched on name + DOB.",
                               "ledger:E000011 (Marla Denny, registration)"))
    pkg = specgen.generate_spec([], store, "delphi")
    policy = next(r for r in pkg.spec["rules"] if r["id"] == "SAFETY-IDENTITY-MERGE")
    assert policy["value"] == "route_to_reconciliation"
    assert not any(r["predicate"] == "merge_policy" and r["value"] == "auto_merge"
                   for r in pkg.spec["rules"])
    assert pkg.spec["policy_overrides"], "the overridden claim must stay visible"
    unknowns = {(u["subject"], u["predicate"]) for u in pkg.spec["known_unknowns"]}
    assert ("identity", "merge_decisions") in unknowns


def test_registry_dispatch_and_halcyon_default():
    assert "halcyon" in reader_names()
    with pytest.raises(KeyError):
        get_reader("nope")
    factory = get_reader("halcyon")
    assert callable(factory)


def test_delphi_export_stages_through_generated_spec(tmp_path):
    from testbed.delphi import generate
    out = tmp_path / "delphi"
    generate(out, seed=7, patients=12)
    layouts, _v = profiler_mod.parse_layouts_dat((out / "LAYOUTS.DAT").read_text())

    # Per-kind key fields, as the recorded interview's layout claims carry:
    # ACCT is not a key for files that have none (dictionaries, journal).
    key_fields = {
        "APPT": {"S": "APPT"}, "BILL": {"B": "CHG"}, "CHGDICT": {"C": "CODE"},
        "DX": {"P": "DXID"}, "DXDICT": {"D": "CODE"}, "ENC": {"V": "VISIT"},
        "JOURNAL": {"J": "SEQ"}, "LAB": {"A": "ACCT", "R": ["ACC", "TEST"]},
        "LABDICT": {"T": "TEST"}, "NOTE": {"N": "NOTE", "C": ["NOTE", "SEQ"]},
        "PHA": {"A": "ACCT", "M": "ORD"}, "PROV": {"D": "CODE"},
        "RAD": {"A": "ACCT", "X": ["ACCT", "EXAM"]}, "REG": {"A": "ACCT"},
    }
    store = claims_mod.ClaimStore()
    files_binding = {}
    for stem, per_rt in sorted(layouts.items()):
        files_binding[stem] = {
            "path": f"{stem}.TXT",
            "key_fields": key_fields[stem],
            "discriminator": {"start": 0, "width": 2, "field": "RT"},
            "layouts": {rt: [{"name": f.name, "start": f.start, "width": f.width,
                              "type": f.type} for f in fields]
                        for rt, fields in per_rt.items()},
        }
    for stem, binding in files_binding.items():
        store.add(claims_mod.Claim(f"file:{stem}", "layout_binding", binding,
                                   "LAYOUTS.DAT v5.0 (estate document)"))
    pkg = specgen.generate_spec([], store, "delphi")
    export = reader_mod.FixedWidthExport(out, pkg.reader_binding)
    records = reader_mod.stage_records(export)
    manifest = json.loads((out / "manifest.json").read_text())
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r["record_type"]] = by_type.get(r["record_type"], 0) + 1
    for stem, count in manifest["counts"].items():
        if stem in by_type:
            assert by_type[stem] == count, stem
    reg = [r for r in records if r["record_type"] == "REG"]
    assert reg and all(r["source_key"] for r in reg)
    assert {r["payload"]["DOB"] for r in reg if r["payload"].get("DOB")}
