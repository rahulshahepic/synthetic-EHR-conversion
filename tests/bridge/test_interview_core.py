"""T-116: deterministic core of the Socratic import builder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

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


# -- subject bindings -----------------------------------------------------------

@pytest.mark.parametrize("bad", [
    ["REG.TXT"],                          # one element
    ["REG.TXT", "DOB", "UNRELATED"],      # three elements
    ["REG.TXT", 12],                      # non-string element
    "REG.TXT.DOB",                        # a bare string, not a pair
    ["REG.TXT", ""],                      # empty element
    None,                                 # missing entirely
])
def test_malformed_bindings_are_rejected_at_the_boundary(bad):
    """PR #43 review, finding 2: a binding's shape is validated once —
    exactly two non-empty strings — at the binding boundary. A malformed
    binding used to sail through tuple() and crash spec generation
    (IndexError / AttributeError) or silently confirm via an ignored
    third element. For a direct bind() caller it raises a clear
    ValueError and records nothing."""
    store = claims_mod.ClaimStore()
    with pytest.raises(ValueError):
        store.bind("profile", bad, predicate="pivot_year")
    assert store.binding_for("profile", "pivot_year") is None


@pytest.mark.parametrize("bad", [
    ["REG.TXT"],                          # one element
    ["REG.TXT", "DOB", "UNRELATED"],      # three elements
    ["REG.TXT", 12],                      # non-string element
    "REG.TXT.DOB",                        # a bare string, not a pair
    ["REG.TXT", ""],                      # empty element
    None,                                 # missing entirely
])
def test_malformed_binding_events_are_flagged_not_fatal(bad):
    """PR #43 round-2 review: one bad binding event must not abort the
    whole ledger replay. The event is skipped and recorded in
    flagged_bindings with a reason; the rest of the ledger replays."""
    events = [
        ledger_mod.LedgerEvent("E000001", "claim",
                               {"subject": "a", "predicate": "b", "value": 1,
                                "source": "dict"}),
        ledger_mod.LedgerEvent(
            "E000002", "binding",
            {"subject": "profile", "predicate": "pivot_year", "binding": bad}),
    ]
    store = claims_mod.ClaimStore.from_ledger(events)
    assert store.resolved_value("a", "b") == 1
    assert store.binding_for("profile", "pivot_year") is None
    assert len(store.flagged_bindings) == 1
    assert store.flagged_bindings[0]["event"] == "E000002"


def test_binding_event_without_subject_is_flagged_not_fatal():
    events = [ledger_mod.LedgerEvent(
        "E000001", "binding",
        {"predicate": "pivot_year", "binding": ["REG.TXT", "DOB"],
         "evidence_refs": ["OBS-0007"]})]
    store = claims_mod.ClaimStore.from_ledger(events)
    assert len(store.flagged_bindings) == 1


def test_binding_event_replays_to_the_store():
    events = [
        ledger_mod.LedgerEvent(
            "E000001", "observation",
            {"obs_id": "OBS-0007", "file": "REG.TXT", "field": "DOB",
             "stats": {"shape_rates": {"YYMMDD": 1.0}}}),
        ledger_mod.LedgerEvent(
            "E000002", "binding",
            {"subject": "profile", "predicate": "pivot_year",
             "binding": ["REG.TXT", "DOB"], "evidence_refs": ["OBS-0007"]}),
    ]
    store = claims_mod.ClaimStore.from_ledger(events)
    assert store.binding_for("profile", "pivot_year") == ("REG.TXT", "DOB")
    assert store.to_json()["bindings"] == [
        {"subject": "profile", "predicate": "pivot_year",
         "binding": ["REG.TXT", "DOB"], "evidence_refs": ["OBS-0007"]}]


def test_binding_event_without_matching_observation_is_flagged():
    """PR #43 round-2 review: a binding event is trusted only when a
    cited data observation actually describes the bound (file, field).
    A binding asserted with no refs — the self-binding route, binding a
    subject to whatever field a later claim happens to cite — is
    skipped and flagged, never recorded."""
    events = [
        ledger_mod.LedgerEvent(
            "E000001", "observation",
            {"obs_id": "OBS-0001", "file": "NOTE.TXT", "field": "TEXT",
             "stats": {"count": 3}}),
        ledger_mod.LedgerEvent(
            "E000002", "binding",
            {"subject": "profile", "predicate": "pivot_year",
             "binding": ["NOTE.TXT", "TEXT"], "evidence_refs": []}),
    ]
    store = claims_mod.ClaimStore.from_ledger(events)
    assert store.binding_for("profile", "pivot_year") is None
    assert len(store.flagged_bindings) == 1


def test_binding_requires_a_predicate_and_rejects_field_subjects():
    """Bindings are keyed by (subject, predicate): no predicate, no
    binding. A field: subject names its own binding, so a recorded
    binding for one is refused instead of silently ignored."""
    store = claims_mod.ClaimStore()
    with pytest.raises(ValueError):
        store.bind("profile", ("REG.TXT", "DOB"))
    with pytest.raises(ValueError):
        store.bind("field:REG.TXT.DOB", ("LAB.TXT", "RESULT"),
                   predicate="convention")


def test_conflicting_rebind_is_a_conflict_not_an_overwrite():
    """A later, different binding for the same (subject, predicate)
    does not silently replace the earlier one: the first stays, the
    conflict is recorded, and the conflicted key binds nothing."""
    store = claims_mod.ClaimStore()
    store.bind("profile", ("REG.TXT", "DOB"), predicate="pivot_year",
               evidence_refs=("OBS-0001",))
    store.bind("profile", ("NOTE.TXT", "TEXT"), predicate="pivot_year",
               evidence_refs=("OBS-0002",))
    assert store.bindings[("profile", "pivot_year")] == ("REG.TXT", "DOB")
    assert store.binding_for("profile", "pivot_year") is None
    assert store.to_json()["binding_conflicts"] == [
        {"subject": "profile", "predicate": "pivot_year",
         "kept": ["REG.TXT", "DOB"], "rejected": [["NOTE.TXT", "TEXT"]]}]


def test_canon_does_not_reorder_non_keying_key_fields():
    """PR #43 round-2 review: _canon sorting key_fields is scoped to
    identity/keying_story. An ordered composite key elsewhere (a layout
    binding's key_fields list) keeps its order: swapped parts are a
    different value and open a dispute."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim("file:X", "layout_binding",
                               {"key_fields": ["ACCT", "DATE"]}, "layouts A"))
    store.add(claims_mod.Claim("file:X", "layout_binding",
                               {"key_fields": ["DATE", "ACCT"]}, "layouts B"))
    assert store.dispute("file:X", "layout_binding") is not None


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


# -- round-4 review: keying contradiction, binding case, binding refs ---------

_FIELDS = ["LAB.TXT.ACCT", "REG.TXT.ACCT"]


@pytest.mark.parametrize("claim_td,resolution_td", [(False, True), (True, False)])
def test_keying_winner_must_not_contradict_the_resolution(claim_td, resolution_td):
    """PR #43 round-4 review: values_match credited a claim as the
    winner of a resolution whose true_duplicates flag the claim
    explicitly contradicted — the claim stated false, the resolution
    recorded true (or the reverse), and the claim still lent the
    resolved value its provenance. A flag present on BOTH sides must
    agree; only an absent flag may be ignored."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": _FIELDS, "master_index": False,
         "true_duplicates": claim_td},
        "DATADICT.TXT v4.1", source_kind="dictionary"))
    store.resolve("identity", "keying_story",
                  {"key_fields": _FIELDS, "master_index": False,
                   "true_duplicates": resolution_td},
                  "ledger answers", evidence_refs=())
    # No claim is credited as the winner: the provenance string
    # carries only the resolution's source, no claim source prefix.
    assert store.provenance("identity", "keying_story") == \
        "dispute resolved via ledger answers"


def test_keying_claim_omitting_a_flag_still_matches():
    """The other half of the rule: a claim that never mentions
    true_duplicates states the core story a resolution later extends
    — it is still the winner (the resolution's added fact simply does
    not inherit the claim's confirmation; see the specgen tests)."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": _FIELDS, "master_index": False},
        "DATADICT.TXT v4.1", source_kind="dictionary"))
    store.resolve("identity", "keying_story",
                  {"key_fields": _FIELDS, "master_index": False,
                   "true_duplicates": True},
                  "ledger answers", evidence_refs=())
    assert store.provenance("identity", "keying_story") == \
        "DATADICT.TXT v4.1; dispute resolved via ledger answers"


def test_keying_claim_omitting_master_index_still_matches():
    """master_index absent reads as False (the validator and the
    scorecard both treat it so): a claim omitting the flag states the
    same story as a resolution spelling out False, and keeps its
    winner attribution."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "identity", "keying_story", {"key_fields": _FIELDS},
        "DATADICT.TXT v4.1", source_kind="dictionary"))
    store.resolve("identity", "keying_story",
                  {"key_fields": _FIELDS, "master_index": False},
                  "ledger answers", evidence_refs=())
    assert store.provenance("identity", "keying_story") == \
        "DATADICT.TXT v4.1; dispute resolved via ledger answers"


def test_binding_case_is_normalized_no_false_conflict():
    """PR #43 round-4 review, the exact repro: record the unit binding
    in the estate's uppercase, then again in lowercase citing the same
    observation. bind() compared case-sensitively while the evidence
    checks match case-insensitively, so the second record registered
    as a CONFLICT and the unit rule silently lost data confirmation.
    Case is normalized at the boundary: same binding, no conflict."""
    store = claims_mod.ClaimStore()
    store.bind("unit:POT", ("LABDICT.TXT", "UNIT"),
               evidence_refs=("OBS-0073",), predicate="unit")
    store.bind("unit:POT", ("labdict.txt", "unit"),
               evidence_refs=("OBS-0073",), predicate="unit")
    assert store.binding_conflicts == {}
    assert store.binding_for("unit:POT", "unit") == ("LABDICT.TXT", "UNIT")
    assert store.to_json()["bindings"] == [
        {"subject": "unit:POT", "predicate": "unit",
         "binding": ["LABDICT.TXT", "UNIT"], "evidence_refs": ["OBS-0073"]}]


def test_bind_rejects_non_string_evidence_refs():
    """PR #43 round-4 review: bind() stored whatever refs it was
    handed; a non-string ref later crashed the generator's matchers
    (TypeError from a regex match on an int). The boundary validates:
    a direct bind() with a non-string ref raises and records nothing."""
    store = claims_mod.ClaimStore()
    with pytest.raises(ValueError):
        store.bind("profile", ("REG.TXT", "DOB"),
                   evidence_refs=(7, "OBS-0001"), predicate="pivot_year")
    assert store.binding_for("profile", "pivot_year") is None
    assert store.binding_refs == {}


def test_binding_event_filters_non_string_refs_and_keeps_the_valid_one():
    """Ledger replay is forgiving where bind() is strict: a binding
    event citing [7, 'OBS-0007'] records the binding with only the
    usable ref, and generation proceeds. A binding whose refs are ALL
    unusable is malformed — skipped and flagged like any bad event."""
    events = [
        ledger_mod.LedgerEvent(
            "E000001", "observation",
            {"obs_id": "OBS-0007", "file": "REG.TXT", "field": "DOB",
             "stats": {"shape_rates": {"YYMMDD": 1.0}}}),
        ledger_mod.LedgerEvent(
            "E000002", "binding",
            {"subject": "profile", "predicate": "pivot_year",
             "binding": ["REG.TXT", "DOB"],
             "evidence_refs": [7, {"id": "OBS-0007"}, "OBS-0007"]}),
        ledger_mod.LedgerEvent(
            "E000003", "binding",
            {"subject": "profile", "predicate": "merge_window_days",
             "binding": ["REG.TXT", "DOB"], "evidence_refs": [[7]]}),
    ]
    store = claims_mod.ClaimStore.from_ledger(events)
    assert store.binding_for("profile", "pivot_year") == ("REG.TXT", "DOB")
    assert store.to_json()["bindings"] == [
        {"subject": "profile", "predicate": "pivot_year",
         "binding": ["REG.TXT", "DOB"], "evidence_refs": ["OBS-0007"]}]
    assert store.binding_for("profile", "merge_window_days") is None
    assert [f["event"] for f in store.flagged_bindings] == ["E000003"]
