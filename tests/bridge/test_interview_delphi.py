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
    # comparing estate documents (DATADICT.TXT vs LAYOUTS.DAT). Document
    # evidence earns the dictionary kind, never profiler-data: since the
    # PR #42 round-4 fixes the profiler-data kind requires subject-bound
    # data confirmation, and since round 5 the grader names this verdict
    # for what it is — caught by document comparison (docs/delphi-scorecard.md).
    "dict_version_skew": "caught-by-documents",
    "dict_dob_format": "caught-by-profiling",
    "dict_pivot_year": "caught-by-analyst",
    "dict_potassium_unit": "caught-by-analyst",
    "dict_stale_field_fax": "caught-by-documents",
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
    "belief_systems_dictionary_current": "caught-by-documents",
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
                       "routed-to-runtime-question": 4, "caught-by-documents": 3}


def test_single_key_claims_do_not_invent_a_master_index(events):
    """PR #43 review, finding 5: the dictionary's "one account per
    patient" and Tom Reyes's "the L number is the patient" are single-key
    positions — one key_fields entry, master_index false. The estate is
    explicit that no master index exists (the vendor module was never
    bought), so the ledger must not record master_index: true for them."""
    store = claims_mod.ClaimStore.from_ledger(events)
    values = {c.source: c.value for c in store.get("identity", "keying_story")}
    assert values["DATADICT.TXT v4.1"] == {"key_fields": ["REG.TXT.ACCT"],
                                           "master_index": False}
    assert values["ledger:E000050 (Tom Reyes, laboratory)"] == {
        "key_fields": ["LAB.TXT.ACCT"], "master_index": False}


def _keying_spec(value):
    return {"rules": [
        {"id": "R001", "subject": "identity", "predicate": "keying_story",
         "value": value, "provenance": {"kind": "analyst"},
         "data_confirmed": False},
        dict(specgen.MERGE_POLICY_RULE),
    ], "known_unknowns": []}


@pytest.mark.parametrize("value", [
    {"key_fields": ["REG.TXT.SSN4", "REG.TXT.DOB"], "master_index": False},
    {"key_fields": ["NOTE.TXT.TEXT", "BILL.TXT.AMOUNT"], "master_index": False},
    {"key_fields": ["REG.TXT.ACCT", "REG.TXT.DOB"], "master_index": False},
    {"key_fields": ["LAB.TXT.ACCT", "PHA.TXT.ACCT"], "master_index": True},
    {"key_fields": ["REG.TXT.ACCT"], "master_index": False},
    # Round-2 review: demographic names beyond the old exact set, and
    # composite tokens whose non-account part hides in front.
    {"key_fields": ["REG.TXT.SSN", "REG.TXT.ACCT", "LAB.TXT.ACCT"],
     "master_index": False},
    {"key_fields": ["REG.TXT.PATIENT_NAME", "REG.TXT.ACCT", "LAB.TXT.ACCT"],
     "master_index": False},
    {"key_fields": ["LAB.TXT.MRN+REG.TXT.ACCT", "RAD.TXT.ACCT"],
     "master_index": False},
])
def test_keying_position_grades_facts_not_shape(value):
    """PR #43 review, finding 7: the true position is per-department
    account keys with no master index — graded against the expected
    structured facts, not token counts. A demographic key pair, unrelated
    fields, a single-department composite, a master-index story, or a
    single key must NOT earn caught-by-analyst for either identity
    discrepancy."""
    for entry_id in ("dict_registration_account_claim",
                     "belief_lab_account_is_identity"):
        verdict = scorecard.grade_entry({"id": entry_id}, _keying_spec(value))
        assert verdict["verdict"] == "swallowed", (entry_id, value, verdict)


def test_keying_position_master_index_absent_is_the_true_position():
    """PR #43 review, finding 7 (second half): master_index is optional
    in the spec validator, so a departmental story that omits it must
    grade as the true position — not None, not swallowed."""
    spec = _keying_spec({"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"]})
    for entry_id in ("dict_registration_account_claim",
                     "belief_lab_account_is_identity"):
        verdict = scorecard.grade_entry({"id": entry_id}, spec)
        assert verdict["verdict"] == "caught-by-analyst", (entry_id, verdict)


def test_duplicate_charts_requires_the_resolved_fact_recorded():
    """PR #43 review, finding 6: routed requires the keying story to
    record the resolved fact (true_duplicates: true). A keying rule plus
    the merge policy alone overstates what was resolved."""
    plain = _keying_spec({"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"],
                          "master_index": False})
    verdict = scorecard.grade_entry({"id": "disagreement_duplicate_charts"}, plain)
    assert verdict["verdict"] == "swallowed"
    recorded = _keying_spec({"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"],
                             "master_index": False, "true_duplicates": True})
    verdict = scorecard.grade_entry({"id": "disagreement_duplicate_charts"}, recorded)
    assert verdict["verdict"] == "routed-to-runtime-question"


@pytest.mark.parametrize("value", [
    # true_duplicates recorded on a FALSE keying story resolves nothing:
    {"key_fields": ["REG.TXT.SSN4", "REG.TXT.DOB"],
     "master_index": True, "true_duplicates": True},
    {"key_fields": ["REG.TXT.SSN4", "REG.TXT.DOB"],
     "master_index": False, "true_duplicates": True},
    {"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"],
     "master_index": True, "true_duplicates": True},
])
def test_duplicate_charts_also_requires_the_true_keying_position(value):
    """PR #43 round-2 review: true_duplicates alone used to earn
    "routed" whatever the keying story said. Routing also requires
    _keying_position == truth."""
    verdict = scorecard.grade_entry(
        {"id": "disagreement_duplicate_charts"}, _keying_spec(value))
    assert verdict["verdict"] == "swallowed", verdict


def test_duplicate_charts_grader_reads_its_truth_from_the_check(monkeypatch):
    """PR #43 round-4 review: the duplicate-charts grader graded
    against a hardcoded {'account_field': 'ACCT', 'min_departments': 2}
    copy instead of the entry's own keying_truth in CHECKS, so the
    hardcoded copy could drift from the data. A variant truth — a
    different account field, a wider department span — must change
    the grade."""
    spec = _keying_spec({"key_fields": ["REG.TXT.CHART", "LAB.TXT.CHART",
                                        "BILL.TXT.CHART"],
                         "master_index": False, "true_duplicates": True})
    verdict = scorecard.grade_entry({"id": "disagreement_duplicate_charts"}, spec)
    assert verdict["verdict"] == "swallowed"  # default truth keys on ACCT
    variant = dict(scorecard.CHECKS["disagreement_duplicate_charts"])
    variant["keying_truth"] = {"account_field": "CHART", "min_departments": 3}
    monkeypatch.setitem(scorecard.CHECKS, "disagreement_duplicate_charts",
                        variant)
    verdict = scorecard.grade_entry({"id": "disagreement_duplicate_charts"}, spec)
    assert verdict["verdict"] == "routed-to-runtime-question"


def test_keying_rule_keeps_its_analyst_provenance(pkg):
    """PR #43 round-2 review: the resolution adds true_duplicates on
    top of Greg Holt's claimed story, so exact-value matching found no
    winning claim and the rule's ref collapsed to the bare resolution.
    The ref must keep the analyst attribution (match on the keying
    core: key_fields + master_index)."""
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "keying_story")
    assert rule["provenance"]["ref"].startswith(
        "ledger:E000066 (Greg Holt, systems); dispute resolved via")


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
