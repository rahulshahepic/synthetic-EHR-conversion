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
    # The (subject, predicate)-level binding: profile/pivot_year
    # confirms via REG.TXT.DOB.
    store.bind("profile", ("REG.TXT", "DOB"), evidence_refs=("OBS-0042",),
               predicate="pivot_year")
    return store


def _seed_layout(store: claims_mod.ClaimStore, path: str,
                 fields: tuple[str, ...] = ("ACCT",)):
    """Record the estate layout evidence a real interview produces —
    a dictionary-kind layout claim from the shipped layouts file —
    so keying-story validation has the estate's fields on record
    (PR #43 round-4 review: a key field validates only against estate
    evidence for its file, never by shape alone)."""
    store.add(claims_mod.Claim(
        f"file:{path.split('.')[0]}", "layout_binding",
        {"path": path, "layouts": {"S": [{"name": f} for f in fields]}},
        "LAYOUTS.DAT v5.0 (estate document)", source_kind="dictionary"))


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


def test_keying_story_structured_value_becomes_the_rule():
    store = _store()
    _seed_layout(store, "REG.TXT")
    _seed_layout(store, "LAB.TXT")
    story = {"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"],
             "master_index": False}
    store.add(claims_mod.Claim("identity", "keying_story", story,
                               "ledger:E000012 (Greg Holt, systems)"))
    pkg = specgen.generate_spec([], store, "delphi")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "keying_story")
    assert rule["value"] == story
    assert not any(o["predicate"] == "keying_story"
                   for o in pkg.spec["policy_overrides"])


@pytest.mark.parametrize("text", [
    # The two phrasings the old merge-language regex let through (T-121):
    "link any two charts sharing SSN4+DOB without review",
    "collapse duplicates on SSN4+DOB automatically",
    "auto-merge any two charts sharing SSN4+DOB",
    "Departmental accounts matched on name + DOB.",
])
def test_keying_story_free_text_is_flagged_never_a_rule(text):
    """A keying story is a structured value. Free text — anodyne or an
    instruction — is flagged in policy_overrides and surfaces as a known
    unknown; it never enters the spec as a rule."""
    store = _store()
    store.add(claims_mod.Claim("identity", "keying_story", text,
                               "ledger:E000012"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])
    assert ("identity", "keying_story") in {
        (u["subject"], u["predicate"]) for u in pkg.spec["known_unknowns"]}


@pytest.mark.parametrize("bad", [
    {"key_fields": ["SSN4 DOB"]},                                   # phrase in a token
    {"key_fields": ["REG.TXT.ACCT"], "action": "merge automatically"},  # extra key
    {"key_fields": []},                                             # no fields
    {"key_fields": ["REG.TXT.ACCT"], "master_index": "no"},         # non-bool flag
    {"key_fields": ["REG.TXT.ACCT"], "true_duplicates": "yes"},     # non-bool flag
])
def test_keying_story_malformed_structure_is_flagged(bad):
    store = _store()
    # Seed REG.TXT's layout so REG.TXT.ACCT is a real field: the
    # non-bool-flag cases must be rejected by the flag validation,
    # not incidentally by a missing-evidence field rejection.
    _seed_layout(store, "REG.TXT")
    store.add(claims_mod.Claim("identity", "keying_story", bad,
                               "ledger:E000012"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])


@pytest.mark.parametrize("token", [
    # One token, no whitespace — an instruction smuggled as a field name
    # (PR #43 review: the old grammar banned only whitespace).
    "auto-merge-any-two-charts-sharing-SSN4+DOB-without-review",
    "collapse_duplicates_on_SSN4+DOB_automatically",
])
def test_keying_story_instruction_in_one_token_is_flagged(token):
    """Key field tokens must match the strict field-reference grammar
    (uppercase FILE.FIELD segments, optional + composites). A lowercase
    instruction-shaped token is not a field reference: the story is
    flagged, never a rule."""
    store = _store()
    store.add(claims_mod.Claim("identity", "keying_story",
                               {"key_fields": [token], "master_index": False},
                               "ledger:E000012"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])
    assert ("identity", "keying_story") in {
        (u["subject"], u["predicate"]) for u in pkg.spec["known_unknowns"]}


def test_keying_story_field_order_is_canonical_not_a_dispute():
    """The same key fields in a different order are the same story:
    no dispute opens, and the rule carries the fields sorted (PR #43
    review: _canon kept list order, so swapped fields read as two
    different values and the keying rule vanished into a known unknown)."""
    store = claims_mod.ClaimStore()
    _seed_layout(store, "REG.TXT")
    _seed_layout(store, "LAB.TXT")
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["REG.TXT.ACCT", "LAB.TXT.ACCT"], "master_index": False},
        "DATADICT.TXT v4.1", source_kind="dictionary"))
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"], "master_index": False},
        "ledger:E000012 (Greg Holt, systems)", source_kind="analyst"))
    assert store.dispute("identity", "keying_story") is None
    pkg = specgen.generate_spec([], store, "delphi")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "keying_story")
    assert rule["value"] == {"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"],
                             "master_index": False}


def test_non_field_subject_confirms_only_via_recorded_binding():
    """T-121: the generator carries no per-source binding table. A
    subject from another source (a Halcyon-shaped registration file the
    generator has never heard of) is data-confirmed when the interview
    recorded the subject-level binding for it — and not without it.
    The binding belongs to the subject, never to the claim."""
    events = [ledger_mod.LedgerEvent(
        "E000001", "observation",
        {"obs_id": "OBS-0009", "file": "CHART.TXT", "field": "BIRTHDATE",
         "stats": {"shape_rates": {"YYMMDD": 1.0}}})]
    bound = claims_mod.ClaimStore()
    bound.add(claims_mod.Claim("profile", "pivot_year", 30, "ledger:E000002",
                               source_kind="analyst",
                               evidence_refs=("OBS-0009",)))
    bound.bind("profile", ("CHART.TXT", "BIRTHDATE"),
               evidence_refs=("OBS-0009",), predicate="pivot_year")
    rule = specgen.generate_spec(events, bound, "halcyon").spec["rules"][0]
    assert rule["data_confirmed"] is True

    unbound = claims_mod.ClaimStore()
    unbound.add(claims_mod.Claim("profile", "pivot_year", 30, "ledger:E000002",
                                 source_kind="analyst",
                                 evidence_refs=("OBS-0009",)))
    rule = specgen.generate_spec(events, unbound, "halcyon").spec["rules"][0]
    assert rule["data_confirmed"] is False


def _dob_events():
    return [ledger_mod.LedgerEvent(
        "E000001", "observation",
        {"obs_id": "OBS-0009", "file": "REG.TXT", "field": "DOB",
         "stats": {"shape_rates": {"YYMMDD": 1.0}}})]


def test_binding_for_one_predicate_does_not_confirm_another():
    """PR #43 round-2 review: bindings are keyed by (subject,
    predicate). The DOB observation that backs profile/pivot_year must
    not "confirm" an unrelated profile predicate (merge_window_days)
    that happens to cite the same observation."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim("profile", "merge_window_days", 0,
                               "ledger:E000002", source_kind="analyst",
                               evidence_refs=("OBS-0009",)))
    store.bind("profile", ("REG.TXT", "DOB"), evidence_refs=("OBS-0009",),
               predicate="pivot_year")
    rule = specgen.generate_spec(_dob_events(), store, "halcyon").spec["rules"][0]
    assert rule["predicate"] == "merge_window_days"
    assert rule["data_confirmed"] is False


def test_binding_without_backing_evidence_confirms_nothing():
    """A binding asserted with no refs — or refs to an observation of
    some other field — is a self-binding: the claim citing the bound
    field's observation still does not confirm, because the binding
    itself was never backed by that observation."""
    events = [ledger_mod.LedgerEvent(
        "E000001", "observation",
        {"obs_id": "OBS-0010", "file": "NOTE.TXT", "field": "TEXT",
         "stats": {"count": 5}})]
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim("profile", "pivot_year", 50,
                               "ledger:E000002", source_kind="analyst",
                               evidence_refs=("OBS-0010",)))
    store.bind("profile", ("NOTE.TXT", "TEXT"), evidence_refs=(),
               predicate="pivot_year")
    rule = specgen.generate_spec(events, store, "halcyon").spec["rules"][0]
    assert rule["data_confirmed"] is False


def test_conflicting_binding_events_confirm_nothing():
    """Two different binding events for one (subject, predicate) —
    each backed by its own observation — are a conflict, not a
    last-one-wins overwrite: neither binding confirms."""
    events = _dob_events() + [
        ledger_mod.LedgerEvent(
            "E000002", "observation",
            {"obs_id": "OBS-0010", "file": "NOTE.TXT", "field": "TEXT",
             "stats": {"count": 5}}),
        ledger_mod.LedgerEvent(
            "E000003", "binding",
            {"subject": "profile", "predicate": "pivot_year",
             "binding": ["REG.TXT", "DOB"], "evidence_refs": ["OBS-0009"]}),
        ledger_mod.LedgerEvent(
            "E000004", "binding",
            {"subject": "profile", "predicate": "pivot_year",
             "binding": ["NOTE.TXT", "TEXT"], "evidence_refs": ["OBS-0010"]}),
        ledger_mod.LedgerEvent(
            "E000005", "claim",
            {"subject": "profile", "predicate": "pivot_year", "value": 50,
             "source": "ledger:E000006", "source_kind": "analyst",
             "evidence_refs": ["OBS-0010"]}),
    ]
    store = claims_mod.ClaimStore.from_ledger(events)
    assert store.binding_for("profile", "pivot_year") is None
    rule = specgen.generate_spec(events, store, "halcyon").spec["rules"][0]
    assert rule["data_confirmed"] is False


@pytest.mark.parametrize("token", [
    "AUTO_MERGE.ALL_CHARTS_SHARING_SSN4_WITHOUT_REVIEW",  # 2 segments
    "MERGE.ALL",                                          # 2 segments
])
def test_keying_story_two_segment_instruction_token_is_flagged(token):
    """PR #43 round-2 review: the fallback grammar requires a full
    FILE.EXT.FIELD reference; a two-segment uppercase token shaped
    like an instruction is flagged, not accepted as a field."""
    store = _store()
    store.add(claims_mod.Claim("identity", "keying_story",
                               {"key_fields": [token], "master_index": False},
                               "ledger:E000012"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])


def test_keying_story_validated_against_the_estates_fields():
    """When the estate's layouts are on record, a key field must name
    a field that actually exists there: MERGE.ALL.CHARTS passes the
    three-segment shape but names no Delphi field, so it is flagged.
    The real departmental story in the same store still becomes the
    rule."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "file:REG", "layout_binding",
        {"path": "REG.TXT",
         "layouts": {"A": [{"name": "ACCT"}, {"name": "DOB"}]}},
        "LAYOUTS.DAT v5.0 (estate document)", source_kind="dictionary"))
    store.add(claims_mod.Claim("identity", "keying_story",
                               {"key_fields": ["MERGE.ALL.CHARTS"],
                                "master_index": False},
                               "ledger:E000012"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])
    good = claims_mod.ClaimStore()
    good.add(claims_mod.Claim(
        "file:REG", "layout_binding",
        {"path": "REG.TXT",
         "layouts": {"A": [{"name": "ACCT"}, {"name": "DOB"}]}},
        "LAYOUTS.DAT v5.0 (estate document)", source_kind="dictionary"))
    good.add(claims_mod.Claim("identity", "keying_story",
                              {"key_fields": ["REG.TXT.ACCT"],
                               "master_index": False},
                              "ledger:E000012"))
    pkg = specgen.generate_spec([], good, "delphi")
    assert any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])


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


# -- round-4 review: provenance of resolution-added facts ----------------------

_KEY_FIELDS = ["LAB.TXT.ACCT", "REG.TXT.ACCT"]


def _layout_event(event_id: str, stem: str, path: str) -> ledger_mod.LedgerEvent:
    return ledger_mod.LedgerEvent(event_id, "claim", {
        "subject": f"file:{stem}", "predicate": "layout_binding",
        "value": {"path": path,
                  "layouts": {"S": [{"name": "ACCT"}, {"name": "DOB"}]}},
        "source": "LAYOUTS.DAT v5.0 (estate document)",
        "source_kind": "dictionary"})


def _keying_ledger(claim_value, resolution_value, resolution_refs=()):
    """A minimal interview ledger for the keying story: a DOB
    observation, the identity/keying_story binding backed by it, the
    estate layouts, one keying claim citing the observation, and a
    resolution."""
    return [
        ledger_mod.LedgerEvent("E000001", "observation",
                               {"obs_id": "OBS-0001", "file": "REG.TXT",
                                "field": "DOB",
                                "stats": {"shape_rates": {"YYMMDD": 1.0}}}),
        ledger_mod.LedgerEvent("E000002", "binding",
                               {"subject": "identity",
                                "predicate": "keying_story",
                                "binding": ["REG.TXT", "DOB"],
                                "evidence_refs": ["OBS-0001"]}),
        _layout_event("E000003", "REG", "REG.TXT"),
        _layout_event("E000004", "LAB", "LAB.TXT"),
        ledger_mod.LedgerEvent("E000005", "claim",
                               {"subject": "identity",
                                "predicate": "keying_story",
                                "value": claim_value,
                                "source": "OBS-0001 (REG.TXT DOB distribution)",
                                "source_kind": "profiler-data",
                                "evidence_refs": ["OBS-0001"]}),
        ledger_mod.LedgerEvent("E000006", "resolve",
                               {"subject": "identity",
                                "predicate": "keying_story",
                                "value": resolution_value,
                                "source": "ledger answers",
                                "claimed_by": "Greg Holt, systems",
                                "source_kind": "analyst",
                                "evidence_refs": list(resolution_refs)}),
    ]


def _keying_rule(events):
    store = claims_mod.ClaimStore.from_ledger(events)
    pkg = specgen.generate_spec(events, store, "delphi")
    return next(r for r in pkg.spec["rules"] if r["predicate"] == "keying_story")


@pytest.mark.parametrize("claim_td,resolution_td", [(False, True), (True, False)])
def test_contradicted_claim_lends_no_provenance(claim_td, resolution_td):
    """PR #43 round-4 review (the reproduced P2): a profiler claim
    stating true_duplicates one way was credited as winner of a
    resolution recording the opposite, and the resolved rule came out
    profiler-data + data_confirmed on the claim's evidence. A
    contradicted claim is not the winner: the rule carries the
    resolution's own provenance and no data confirmation."""
    claim = {"key_fields": _KEY_FIELDS, "master_index": False,
             "true_duplicates": claim_td}
    resolved = {"key_fields": _KEY_FIELDS, "master_index": False,
                "true_duplicates": resolution_td}
    rule = _keying_rule(_keying_ledger(claim, resolved))
    assert rule["value"]["true_duplicates"] is resolution_td
    assert rule["provenance"]["kind"] == "analyst"
    assert rule["data_confirmed"] is False


def test_resolution_added_fact_is_not_confirmed_by_the_winner():
    """The claim stated the keying core but never mentioned
    true_duplicates; the resolution added it. The winner's profiler
    evidence confirms the facts the winner stated — it cannot confirm
    a fact it never mentioned, so the emitted value is not
    data-confirmed and the unearned profiler-data kind is demoted to
    the conservative reading of the claim's source."""
    claim = {"key_fields": _KEY_FIELDS, "master_index": False}
    resolved = {"key_fields": _KEY_FIELDS, "master_index": False,
                "true_duplicates": True}
    rule = _keying_rule(_keying_ledger(claim, resolved))
    assert rule["data_confirmed"] is False
    assert rule["provenance"]["kind"] == "analyst"


def test_resolution_added_fact_confirmed_by_the_resolutions_own_evidence():
    """Same shape, but the resolution cites the binding's observation
    itself: both routes confirm — the winner's for the stated core,
    the resolution's for the added fact — and the rule confirms."""
    claim = {"key_fields": _KEY_FIELDS, "master_index": False}
    resolved = {"key_fields": _KEY_FIELDS, "master_index": False,
                "true_duplicates": True}
    rule = _keying_rule(_keying_ledger(claim, resolved,
                                       resolution_refs=("OBS-0001",)))
    assert rule["data_confirmed"] is True
    assert rule["provenance"]["kind"] == "profiler-data"


def test_exactly_stated_keying_story_still_confirms():
    """Control: claim and resolution state the identical story,
    flag included — the winner route confirms as before."""
    story = {"key_fields": _KEY_FIELDS, "master_index": False,
             "true_duplicates": True}
    rule = _keying_rule(_keying_ledger(story, dict(story)))
    assert rule["data_confirmed"] is True
    assert rule["provenance"]["kind"] == "profiler-data"


# -- round-4 review: the key-field allowlist -----------------------------------

def test_analyst_layout_claim_cannot_mint_key_fields():
    """PR #43 round-4 review: _known_fields treated EVERY layout
    claim as estate truth. An analyst claim inventing the layout
    AUTO_MERGE.ALL / CHARTS_SHARING_SSN4 made that instruction-shaped
    key validate. Only dictionary/document-kind layout claims feed
    the allowlist — an interviewee's assertion is not the estate."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "file:AUTO_MERGE", "layout_binding",
        {"path": "AUTO_MERGE.ALL",
         "layouts": {"X": [{"name": "CHARTS_SHARING_SSN4"}]}},
        "ledger:E000099 (an analyst)", source_kind="analyst"))
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["AUTO_MERGE.ALL.CHARTS_SHARING_SSN4"],
         "master_index": False},
        "ledger:E000099 (an analyst)", source_kind="analyst"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])

    # Control: the same layout as estate (dictionary) evidence makes
    # the same field reference a real field.
    store2 = claims_mod.ClaimStore()
    store2.add(claims_mod.Claim(
        "file:AUTO_MERGE", "layout_binding",
        {"path": "AUTO_MERGE.ALL",
         "layouts": {"X": [{"name": "CHARTS_SHARING_SSN4"}]}},
        "LAYOUTS.DAT v5.0 (estate document)", source_kind="dictionary"))
    store2.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["AUTO_MERGE.ALL.CHARTS_SHARING_SSN4"],
         "master_index": False},
        "ledger:E000099 (an analyst)", source_kind="analyst"))
    pkg2 = specgen.generate_spec([], store2, "delphi")
    assert any(r["predicate"] == "keying_story" for r in pkg2.spec["rules"])


def test_disputed_layout_claim_feeds_no_fields():
    """A layout claim under an open dispute is contested, not estate
    truth: while two dictionary readings of REG.TXT disagree, neither
    side's field list validates a keying story."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "file:REG", "layout_binding",
        {"path": "REG.TXT", "layouts": {"S": [{"name": "ACCT"}]}},
        "LAYOUTS.DAT v5.0", source_kind="dictionary"))
    store.add(claims_mod.Claim(
        "file:REG", "layout_binding",
        {"path": "REG.TXT", "layouts": {"S": [{"name": "OTHER"}]}},
        "DATADICT.TXT v4.1", source_kind="dictionary"))
    _seed_layout(store, "LAB.TXT")
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["REG.TXT.ACCT", "LAB.TXT.ACCT"],
         "master_index": False},
        "ledger:E000012 (Greg Holt, systems)", source_kind="analyst"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])


def test_one_observed_field_does_not_validate_its_whole_file():
    """PR #43 round-4 review: strictness used to flip on globally —
    observing REG.TXT.DOB put the generator in allowlist mode for
    every file, and REG.TXT.ACCT was judged against a set that never
    contained it for the wrong reason while other files' tokens were
    judged against nothing relevant. Strictness is per file: DOB
    observed says nothing about ACCT, so the true story is not yet
    validated — it waits for the estate's layout evidence."""
    events = [ledger_mod.LedgerEvent(
        "E000001", "observation",
        {"obs_id": "OBS-0001", "file": "REG.TXT", "field": "DOB",
         "stats": {"shape_rates": {"YYMMDD": 1.0}}})]
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["REG.TXT.ACCT", "LAB.TXT.ACCT"],
         "master_index": False},
        "ledger:E000012 (Greg Holt, systems)", source_kind="analyst"))
    pkg = specgen.generate_spec(events, store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])


@pytest.mark.parametrize("token", [
    "MERGE.ALL.CHARTS",
    "AUTO_MERGE.ALL.CHARTS_SHARING_SSN4_WITHOUT_REVIEW",
])
def test_keying_token_without_estate_evidence_never_validates(token):
    """PR #43 round-4 review: with no estate fields on record at all,
    a shape-only fallback grammar used to accept any three-segment
    uppercase token — MERGE.ALL.CHARTS validated and the instruction
    became a rule. There is no fallback: no estate evidence for the
    token's file, no validation; the story is flagged instead."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": [token], "master_index": False},
        "ledger:E000012 (Greg Holt, systems)", source_kind="analyst"))
    pkg = specgen.generate_spec([], store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])
    assert ("identity", "keying_story") in {
        (u["subject"], u["predicate"]) for u in pkg.spec["known_unknowns"]}


def test_non_string_claim_refs_do_not_crash_generation():
    """PR #43 round-4 review, defense in depth: claim evidence refs
    replayed from a hand-edited ledger can still carry non-strings
    (claims are not the binding boundary). The confirmation matchers
    must ignore them, not crash on a regex match against an int —
    and the valid ref alongside still confirms."""
    events = [
        ledger_mod.LedgerEvent("E000001", "observation",
                               {"obs_id": "OBS-0001", "file": "REG.TXT",
                                "field": "DOB",
                                "stats": {"shape_rates": {"YYMMDD": 1.0}}}),
        ledger_mod.LedgerEvent("E000002", "binding",
                               {"subject": "profile",
                                "predicate": "pivot_year",
                                "binding": ["REG.TXT", "DOB"],
                                "evidence_refs": ["OBS-0001"]}),
        ledger_mod.LedgerEvent("E000003", "claim",
                               {"subject": "profile",
                                "predicate": "pivot_year", "value": 30,
                                "source": "ledger:E000004 (Marla Denny)",
                                "source_kind": "analyst",
                                "evidence_refs": [7, ["OBS-0001"], "OBS-0001"]}),
    ]
    store = claims_mod.ClaimStore.from_ledger(events)
    pkg = specgen.generate_spec(events, store, "delphi")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is True
