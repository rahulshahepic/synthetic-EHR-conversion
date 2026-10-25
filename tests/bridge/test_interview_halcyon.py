"""T-120: Halcyon re-derivation — recorded interview, generated spec, and
the measured diff against the hand-written control profile."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.interview import claims as claims_mod
from bridge.interview import diff as diff_mod
from bridge.interview import ledger as ledger_mod
from bridge.interview import specgen
from bridge.interview.analysts import AnalystService, EstateReader, StubAnalyst, replay_questions
from bridge.profiles import halcyon as control_profile

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "src/bridge/interview/ledgers/halcyon.jsonl"
SPEC_DIR = ROOT / "src/bridge/interview/specs/halcyon"


@pytest.fixture(scope="module")
def events():
    return ledger_mod.read_events(LEDGER)


@pytest.fixture(scope="module")
def pkg(events):
    return specgen.generate_spec(events, claims_mod.ClaimStore.from_ledger(events), "halcyon")


def test_ledger_replays_to_the_committed_spec(events, pkg):
    assert pkg.spec_json() == (SPEC_DIR / "spec.json").read_text()
    assert pkg.profile_code == (SPEC_DIR / "profile.py").read_text()


def test_stub_replay_byte_for_byte(events, tmp_path):
    stub = json.loads((SPEC_DIR / "stub_analysts.json").read_text())
    analysts = {aid: StubAnalyst(id=aid, name=c["name"], answers=c["answers"],
                                 blind_spots=c["blind_spots"],
                                 outside_response=c["outside_response"])
                for aid, c in stub.items()}
    svc = AnalystService(analysts, EstateReader([tmp_path]))
    assert replay_questions(events, svc) == []


def test_halcyon_identity_merges_route_to_human(pkg):
    policy = next(r for r in pkg.spec["rules"] if r["id"] == "SAFETY-IDENTITY-MERGE")
    assert policy["value"] == "route_to_reconciliation"
    ns: dict = {}
    exec(pkg.profile_code, ns)
    assert ns["MERGE_POLICY"] == "route_to_reconciliation"
    assert ns["READER"] == "halcyon"


def test_diff_against_handwritten_control(pkg):
    gen_ns: dict = {}
    exec(pkg.profile_code, gen_ns)
    control_ns = {k: getattr(control_profile, k) for k in diff_mod.FACT_SUBJECTS}
    report = diff_mod.diff_profiles(gen_ns, control_ns, pkg.spec)
    by_fact = {e["fact"]: e["status"] for e in report["entries"]}
    assert by_fact["SYSTEM_ORG"] == "matched"
    assert by_fact["MRN_SYSTEM"] == "matched"
    assert by_fact["FACILITY_TZ[FAC3]"] == "matched"   # Denver, via the interface engineer
    assert by_fact["VITAL_UNITS[FAC3]"] == "matched"   # metric, ditto
    assert by_fact["CHARGE_CENTS_FROM"] == "matched"   # 2012-01-01 cutover recovered
    # The feed-only window's length was claimed as 30 (lab) and 0 (HIM, from
    # the dictionary) and never settled: it must show as disputed, not as a
    # quietly matched or invented value.
    assert by_fact["LAB_FEED_ONLY_DAYS"] == "disputed"
    assert report["counts"] == {"matched": 9, "disputed": 1}


def test_crosswalk_coverage_compared(pkg, events):
    store = claims_mod.ClaimStore.from_ledger(events)
    gaps = {c.subject[len("codeset:"):] for c in store.claims
            if c.predicate == "documented_gap"}
    control_sets = sorted(p.stem for p in
                          (ROOT / "src/bridge/terminology/data").glob("*.csv"))
    report = diff_mod.diff_crosswalks(pkg.crosswalks, gaps, control_sets)
    assert report["control_total"] == 12
    assert report["documented_gaps"] == ["formulary_rxnorm"]
    assert report["covered"] == []
    assert len(report["missing"]) == 11
