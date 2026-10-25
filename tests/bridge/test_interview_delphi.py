"""T-119: the recorded Delphi interview, its generated spec, and the
discrepancy scorecard (16 grading entries, verdicts computed)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.interview import claims as claims_mod
from bridge.interview import ledger as ledger_mod
from bridge.interview import reader as reader_mod
from bridge.interview import scorecard, specgen
from bridge.interview.analysts import AnalystService, EstateReader, StubAnalyst, replay_questions

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "src/bridge/interview/ledgers/delphi.jsonl"
SPEC_DIR = ROOT / "src/bridge/interview/specs/delphi"

EXPECTED = {
    # The version skew and the stale FAX field were both established by
    # comparing estate documents (DATADICT.TXT vs LAYOUTS.DAT). Since the
    # PR #42 round-4 fixes, document evidence earns the dictionary kind,
    # never profiler-data: the profiler-data kind requires subject-bound
    # data confirmation. The grader credits no "caught" verdict to a
    # dictionary-kind rule, so these grade as swallowed — the spec still
    # carries the true position in both cases (see docs/delphi-scorecard.md).
    "dict_version_skew": "swallowed",
    "dict_dob_format": "caught-by-profiling",
    "dict_pivot_year": "caught-by-analyst",
    "dict_potassium_unit": "caught-by-analyst",
    "dict_stale_field_fax": "swallowed",
    "dict_undocumented_yday": "caught-by-analyst",
    "dict_undocumented_allergy_field": "caught-by-analyst",
    "dict_appt_status_incomplete": "routed-to-runtime-question",
    "dict_registration_account_claim": "caught-by-analyst",
    "belief_lab_account_is_identity": "caught-by-analyst",
    # The profiler's value-shape claim (OBS-0060: RESULT carries non-numeric
    # text) now disputes Tom Reyes's bench-error belief, so it routes to a
    # runtime question instead of being swallowed (see PR #42 review fixes).
    "belief_lab_nonnumeric_bench_error": "routed-to-runtime-question",
    "belief_registration_merges_routine": "routed-to-runtime-question",
    "belief_pharmacy_misc_meds_skippable": "caught-by-analyst",
    # Holt's "the dictionary is current" belief is refuted by the same
    # version-skew rule, so it shares that rule's verdict.
    "belief_systems_dictionary_current": "swallowed",
    "disagreement_pivot_year": "caught-by-analyst",
    "disagreement_duplicate_charts": "routed-to-runtime-question",
}


@pytest.fixture(scope="module")
def events():
    return ledger_mod.read_events(LEDGER)


@pytest.fixture(scope="module")
def pkg(events):
    return specgen.generate_spec(events, claims_mod.ClaimStore.from_ledger(events), "delphi")


def test_ledger_replays_to_the_committed_spec(events, pkg):
    assert pkg.spec_json() == (SPEC_DIR / "spec.json").read_text()
    assert pkg.profile_code == (SPEC_DIR / "profile.py").read_text()
    assert json.loads((SPEC_DIR / "reader_binding.json").read_text()) == pkg.reader_binding


def test_stub_replay_byte_for_byte(events, tmp_path):
    stub = json.loads((SPEC_DIR / "stub_analysts.json").read_text())
    analysts = {aid: StubAnalyst(id=aid, name=c["name"], answers=c["answers"],
                                 blind_spots=c["blind_spots"],
                                 outside_response=c["outside_response"])
                for aid, c in stub.items()}
    svc = AnalystService(analysts, EstateReader([tmp_path]))
    assert replay_questions(events, svc) == []


def test_delphi_identity_merges_route_to_human(pkg):
    policy = next(r for r in pkg.spec["rules"] if r["id"] == "SAFETY-IDENTITY-MERGE")
    assert policy["value"] == "route_to_reconciliation"
    assert pkg.spec["policy_overrides"], "Marla's routine-merge claim must be overridden visibly"
    ns: dict = {}
    exec(pkg.profile_code, ns)
    assert ns["MERGE_POLICY"] == "route_to_reconciliation"


@pytest.fixture(scope="module")
def verdicts(tmp_path_factory):
    from testbed.delphi import generate
    out = tmp_path_factory.mktemp("delphi-grade")
    generate(out, seed=42, patients=200)
    discrepancies = json.loads((out / "answer_key" / "estate_discrepancies.json").read_text())
    events = ledger_mod.read_events(LEDGER)
    pkg = specgen.generate_spec(events, claims_mod.ClaimStore.from_ledger(events), "delphi")
    return {v["id"]: v["verdict"] for v in scorecard.grade(discrepancies, pkg.spec)}


def test_scorecard_verdicts(verdicts):
    assert verdicts == EXPECTED
    summary = scorecard.summarize([{"verdict": v} for v in verdicts.values()])
    assert summary == {"caught-by-profiling": 1, "caught-by-analyst": 8,
                       "routed-to-runtime-question": 4, "swallowed": 3}


def test_delphi_staging_through_committed_binding(tmp_path):
    from testbed.delphi import generate
    out = tmp_path / "delphi"
    generate(out, seed=42, patients=200)
    binding = json.loads((SPEC_DIR / "reader_binding.json").read_text())
    records = reader_mod.stage_records(reader_mod.FixedWidthExport(out, binding))
    manifest = json.loads((out / "manifest.json").read_text())
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r["record_type"]] = by_type.get(r["record_type"], 0) + 1
    for stem, count in manifest["counts"].items():
        assert by_type.get(stem) == count, stem
