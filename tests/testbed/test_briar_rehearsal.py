"""Acceptance and fault injection for the autonomous Briar rehearsal."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from testbed.briar.generate import generate
from testbed.scenarios.briar import run
from testbed.scenarios.briar_adapter import local_time
from testbed.scenarios.briar_grade import grade


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory):
    out = tmp_path_factory.mktemp("briar-parent") / "run"
    grades = run(out, patients=64, seed=349, repeat=True)
    assert all(g["ok"] for g in grades)
    return out


def test_actual_target_dispositions_and_clinical_values(rehearsal):
    result = json.loads((rehearsal / "corrected_results.json").read_text())
    assert result["verification"]["ok"]
    assert result["readiness"]["decision"] == "NO-GO"
    assert result["source_rows_accounted"] == result["physical_rows"]
    assert result["summary"]["status"] == "completed_with_exceptions"
    assert all(not c.get("rejected", 0) for c in (v["counts"] for v in result["summary"]["by_type"].values()))
    assert all(q["answer"] is None for q in result["questions"])
    loss_check = next(c for c in result["readiness"]["checks"] if c["check"] == "fidelity_loss_signed_off")
    assert loss_check["detail"]["signed"] == {}


def test_native_generated_path_is_staging_only_and_loses_indentation(rehearsal):
    native = json.loads((rehearsal / "native_result.json").read_text())
    assert native["status"] == "staged"
    assert native["target_patients"] == 0
    assert native["leading_note_whitespace_stripped"] == 64


def test_same_ledger_same_spec_and_same_population_replays(rehearsal):
    checks = json.loads((rehearsal / "replay_checks.json").read_text())
    assert all(checks.values())
    base = json.loads((rehearsal / "corrected_results.json").read_text())["target_counts"]
    assert json.loads((rehearsal / "idempotent_results.json").read_text())["target_counts"] == base


def test_committed_discovery_reproduces_spec_and_profiles_actual_source(tmp_path):
    from bridge.interview.claims import ClaimStore
    from bridge.interview.coverage import Inventory
    from bridge.interview.ledger import read_events
    from bridge.interview.profiler import parse_layouts_dat, profile_export
    from bridge.interview.specgen import generate_spec, recorded_inventory
    repo = Path(__file__).resolve().parents[2]
    specdir = repo / "src/bridge/interview/specs/briar"
    events = read_events(repo / "src/bridge/interview/ledgers/briar.jsonl")
    generate(tmp_path / "source", 320, 2626)
    layouts, _ = parse_layouts_dat((tmp_path / "source/LAYOUTS.DAT").read_text())
    report = profile_export(tmp_path / "source", layouts)
    inventory = Inventory.from_profile_report(report, ["lab", "medication", "diagnosis", "charge"])
    assert recorded_inventory(events) == inventory.files
    observations = [{"obs_id": o["id"], **{k: v for k, v in o.items() if k != "id"}} for o in report["observations"]]
    assert [e.payload for e in events if e.type == "observation"] == observations
    pkg = generate_spec(events, ClaimStore.from_ledger(events), "briar", inventory=inventory)
    assert pkg.spec_json() == (specdir / "spec.json").read_text()
    assert pkg.profile_code == (specdir / "profile.py").read_text()


def test_committed_generated_profile_runs_through_stock_dispatch(tmp_path):
    import runpy
    from types import SimpleNamespace
    from bridge.load.client import connect
    from bridge.runs.runner import Runner
    from bridge.runs.store import RunStore
    repo = Path(__file__).resolve().parents[2]
    generate(tmp_path / "source", 32, 2626)
    profile = SimpleNamespace(**runpy.run_path(str(repo / "src/bridge/interview/specs/briar/profile.py")))
    store = RunStore(str(tmp_path / "native.db"))
    client = connect("embedded:" + str(tmp_path / "nimbus.db"))
    try:
        rid = Runner(store, client, profile).start(str(tmp_path / "source"))
        assert store.run(rid)["status"] == "staged"
        assert client.count("Patient")["total"] == 0
        assert sum(sum(v.values()) for v in store.status_counts(rid).values()) == sum(json.loads((tmp_path / "source/manifest.json").read_text())["counts"].values())
    finally:
        store.db.close()
        client.http.close()


def test_source_files_are_seeded_and_repeatable(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, 64, 71)
    generate(b, 64, 71)
    assert {str(p.relative_to(a)): p.read_bytes() for p in a.rglob("*") if p.is_file()} == {str(p.relative_to(b)): p.read_bytes() for p in b.rglob("*") if p.is_file()}


@pytest.mark.parametrize("day,clock", [("20251102", "0130"), ("20260308", "0230"), ("20261010", "2461")])
def test_no_utc_invention_for_dst_or_invalid_clock(day, clock):
    with pytest.raises(ValueError): local_time(day, clock, "America/Chicago")


def test_explicit_midnight_rollover():
    assert local_time("20261010", "2400", "America/Chicago") == "2026-10-11T05:00:00Z"


@pytest.mark.parametrize("fault,expected_check", [
    ("lab_unit", "lab_unit"), ("comparator", "lab_comparator"),
    ("note_indent", "note_bytes_and_order"), ("held_med_active", "medication_status"),
    ("charge_scale", "charge_scale_and_sign"), ("invented_condition", "no_invented_diagnosis"),
    ("extra_target", "target_key_set"),
])
def test_grader_rejects_clinically_wrong_targets(rehearsal, tmp_path, fault, expected_check):
    target = json.loads((rehearsal / "corrected_target.json").read_text())
    if fault == "lab_unit": next(o for o in target["Observation"] if o.get("valueQuantity"))["valueQuantity"]["unit"] = "kg"
    elif fault == "comparator": next(o for o in target["Observation"] if o.get("valueQuantity", {}).get("comparator"))["valueQuantity"].pop("comparator")
    elif fault == "note_indent": target["DocumentReference"][0]["content"] = target["DocumentReference"][0]["content"].replace("\n  PLAN", "\nPLAN")
    elif fault == "held_med_active": next(m for m in target["MedicationRequest"] if m["status"] == "on-hold")["status"] = "active"
    elif fault == "charge_scale": target["ChargeItem"][0]["amount"] /= 100
    elif fault == "invented_condition": next(c for c in target["Condition"] if not c["code"].get("coding"))["code"]["coding"] = [{"system": "ICD-10-CM", "code": "E11.9"}]
    elif fault == "extra_target": target["Patient"].append({**target["Patient"][0], "sourceKey": "invented"})
    (tmp_path / "source/grading").mkdir(parents=True)
    (tmp_path / "source/grading/truth.json").write_bytes((rehearsal / "source/grading/truth.json").read_bytes())
    (tmp_path / "corrected_records.json").write_bytes((rehearsal / "corrected_records.json").read_bytes())
    (tmp_path / "corrected_target.json").write_text(json.dumps(target))
    result = grade(tmp_path)
    assert not result["ok"]
    assert expected_check in {e["check"] for e in result["errors"]}


def test_conversion_can_run_with_grading_reads_forbidden(tmp_path, monkeypatch):
    from testbed.scenarios.briar_discover import discover
    from testbed.scenarios.briar_run import execute
    generate(tmp_path / "source", 32, 19)
    read_text, read_bytes, path_open = Path.read_text, Path.read_bytes, Path.open
    def deny(path):
        if "grading" in path.parts: raise AssertionError("conversion attempted a grading read")
    def text_read(self, *a, **kw): deny(self); return read_text(self, *a, **kw)
    def bytes_read(self, *a, **kw): deny(self); return read_bytes(self, *a, **kw)
    def open_path(self, *a, **kw): deny(self); return path_open(self, *a, **kw)
    monkeypatch.setattr(Path, "read_text", text_read)
    monkeypatch.setattr(Path, "read_bytes", bytes_read)
    monkeypatch.setattr(Path, "open", open_path)
    discover(tmp_path)
    result = execute(tmp_path, runtime_interviews=False)
    assert result["verification"]["ok"]
    # A simulated analyst deferring a clinical question must not turn its
    # held records into silent drops on reprocessing.
    from bridge.load.client import connect
    from bridge.mapping.base import MAPPERS
    from bridge.reconcile.answers import answer
    from bridge.runs.runner import Runner
    from bridge.runs.store import RunStore
    from testbed.scenarios.briar_adapter import install
    profile, _, original = install(tmp_path)
    store = RunStore(str(tmp_path / "rehearsal1.db"))
    client = connect("embedded:" + str(tmp_path / "rehearsal1_nimbus.db"))
    try:
        rid = result["run_id"]
        q = next(q for q in store.questions(rid) if q["kind"] == "briar_unmapped_medication")
        affected = store.question(q["id"])["affected"]
        answer(store, q["id"], "defer", answered_by="simulated:test-pharmacist", rationale="Test-only deferral, no clinical evidence supplied")
        Runner(store, client, profile).execute(rid)
        assert all(store.status_of(rid, a["rtype"], a["source_key"]) == "held" for a in affected)
    finally:
        MAPPERS.update(original)
        store.db.close()
        client.http.close()
