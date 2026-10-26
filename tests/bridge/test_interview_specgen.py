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


def _inventory(*paths: str, fields: tuple[str, ...] = ("ACCT", "DOB"),
               event_id: str = "E000900") -> list[ledger_mod.LedgerEvent]:
    """The profiler's export inventory as a real interview records it —
    an ``inventory`` ledger event — so keying-story validation has the
    estate's fields on record. A key field validates only against
    machine evidence for its file (the inventory or a data
    observation), never by shape and never from a layout claim."""
    return [ledger_mod.LedgerEvent(event_id, "inventory",
                                   {"files": {p: list(fields) for p in paths}})]


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
    story = {"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"],
             "master_index": False}
    store.add(claims_mod.Claim("identity", "keying_story", story,
                               "ledger:E000012 (Greg Holt, systems)"))
    pkg = specgen.generate_spec(_inventory("REG.TXT", "LAB.TXT"), store, "delphi")
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
    # REG.TXT is in the inventory so REG.TXT.ACCT is a real field: the
    # non-bool-flag cases must be rejected by the flag validation,
    # not incidentally by a missing-evidence field rejection.
    store.add(claims_mod.Claim("identity", "keying_story", bad,
                               "ledger:E000012"))
    pkg = specgen.generate_spec(_inventory("REG.TXT"), store, "delphi")
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
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["REG.TXT.ACCT", "LAB.TXT.ACCT"], "master_index": False},
        "DATADICT.TXT v4.1", source_kind="dictionary"))
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["LAB.TXT.ACCT", "REG.TXT.ACCT"], "master_index": False},
        "ledger:E000012 (Greg Holt, systems)", source_kind="analyst"))
    assert store.dispute("identity", "keying_story") is None
    pkg = specgen.generate_spec(_inventory("REG.TXT", "LAB.TXT"), store, "delphi")
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
    """When the profiler's inventory is on record, a key field must
    name a field that actually exists there: MERGE.ALL.CHARTS passes
    the three-segment shape but names no Delphi field, so it is
    flagged. The real departmental story still becomes the rule."""
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim("identity", "keying_story",
                               {"key_fields": ["MERGE.ALL.CHARTS"],
                                "master_index": False},
                               "ledger:E000012"))
    pkg = specgen.generate_spec(_inventory("REG.TXT"), store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])
    good = claims_mod.ClaimStore()
    good.add(claims_mod.Claim("identity", "keying_story",
                              {"key_fields": ["REG.TXT.ACCT"],
                               "master_index": False},
                              "ledger:E000012"))
    pkg = specgen.generate_spec(_inventory("REG.TXT"), good, "delphi")
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
    """The profiler's inventory entry for one file (``stem`` names the
    file's layout subject; only the inventory's path matters here)."""
    return _inventory(path, event_id=event_id)[0]


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


def test_resolution_evidence_does_not_confirm_the_added_fact():
    """PR #43 round-6 review (Claude, reproduced): the resolution
    citing the binding's observation confirmed the true_duplicates it
    added. A field observation measures nothing about how registration
    behaves, so a keying story carrying true_duplicates is never
    data-confirmed, whoever cites the observation."""
    claim = {"key_fields": _KEY_FIELDS, "master_index": False}
    resolved = {"key_fields": _KEY_FIELDS, "master_index": False,
                "true_duplicates": True}
    rule = _keying_rule(_keying_ledger(claim, resolved,
                                       resolution_refs=("OBS-0001",)))
    assert rule["data_confirmed"] is False
    assert rule["provenance"]["kind"] == "analyst"


def test_profiler_labelled_claim_does_not_confirm_true_duplicates():
    """PR #43 round-6 review (Claude, reproduced): a claim labelled
    profiler-data stating the full story, flag included, and citing the
    bound field's observation came out profiler-data + data_confirmed.
    The label is self-declared and the observation measures a field,
    not registration behaviour: unconfirmed, and the unearned kind is
    demoted."""
    story = {"key_fields": _KEY_FIELDS, "master_index": False,
             "true_duplicates": True}
    rule = _keying_rule(_keying_ledger(story, dict(story)))
    assert rule["data_confirmed"] is False
    assert rule["provenance"]["kind"] != "profiler-data"


def test_keying_core_alone_still_confirms():
    """Control: a story with no fact beyond its key fields still
    confirms through the bound observation, as before."""
    story = {"key_fields": _KEY_FIELDS, "master_index": False}
    rule = _keying_rule(_keying_ledger(story, dict(story)))
    assert rule["data_confirmed"] is True
    assert rule["provenance"]["kind"] == "profiler-data"


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


# -- round-5 review: confirmation tracked on the supplying claim ---------------

def _mixed_winner_ledger(profiler_first: bool, resolution_refs=()):
    """Claude's round-5 repro ledger: a profiler-data claim stating the
    keying core and citing the binding's observation; an analyst claim
    stating the complete story (true_duplicates added) with no
    evidence; a resolution to the complete story."""
    obs = ledger_mod.LedgerEvent(
        "E000001", "observation",
        {"obs_id": "OBS-0001", "file": "REG.TXT", "field": "DOB",
         "stats": {"shape_rates": {"YYMMDD": 1.0}}})
    binding = ledger_mod.LedgerEvent(
        "E000002", "binding",
        {"subject": "identity", "predicate": "keying_story",
         "binding": ["REG.TXT", "DOB"], "evidence_refs": ["OBS-0001"]})
    profiler = ledger_mod.LedgerEvent(
        "E000005", "claim",
        {"subject": "identity", "predicate": "keying_story",
         "value": {"key_fields": ["REG.TXT.ACCT"]},
         "source": "OBS-0001 (REG.TXT DOB distribution)",
         "source_kind": "profiler-data", "evidence_refs": ["OBS-0001"]})
    analyst = ledger_mod.LedgerEvent(
        "E000006", "claim",
        {"subject": "identity", "predicate": "keying_story",
         "value": {"key_fields": ["REG.TXT.ACCT"], "true_duplicates": True},
         "source": "ledger:E000007 (Greg Holt, systems)",
         "source_kind": "analyst", "evidence_refs": []})
    claims = [profiler, analyst] if profiler_first else [analyst, profiler]
    return [obs, binding,
            _layout_event("E000003", "REG", "REG.TXT"),
            _layout_event("E000004", "LAB", "LAB.TXT"),
            *claims,
            ledger_mod.LedgerEvent(
                "E000008", "resolve",
                {"subject": "identity", "predicate": "keying_story",
                 "value": {"key_fields": ["REG.TXT.ACCT"],
                           "true_duplicates": True},
                 "source": "ledger answers",
                 "claimed_by": "Greg Holt, systems",
                 "source_kind": "analyst",
                 "evidence_refs": list(resolution_refs)})]


@pytest.mark.parametrize("profiler_first", [True, False])
def test_mixed_winners_partial_confirmation_does_not_leak(profiler_first):
    """PR #43 round-5 review (both reviewers, reproduced): the round-4
    guard asked whether ALL winners were partial, so adding one
    unmeasured analyst claim stating the complete story flipped the
    guard off and let the PARTIAL profiler winner's confirmation cover
    the resolution-added fact. Confirmation belongs to the claim that
    supplied the fact: the complete value is confirmed only by a
    complete winner's evidence or the resolution's own — here neither
    exists, whichever order the claims arrive in."""
    rule = _keying_rule(_mixed_winner_ledger(profiler_first))
    assert rule["value"]["true_duplicates"] is True
    assert rule["data_confirmed"] is False
    assert rule["provenance"]["kind"] == "analyst"


def test_mixed_winners_resolution_evidence_does_not_confirm():
    """Same mixed winners, with the resolution citing the binding's
    observation itself: still unconfirmed — no field observation can
    confirm true_duplicates."""
    rule = _keying_rule(_mixed_winner_ledger(
        True, resolution_refs=("OBS-0001",)))
    assert rule["data_confirmed"] is False


# -- round-5 review: the allowlist reads resolved state, data only -------------

def test_document_quote_observation_does_not_feed_the_allowlist():
    """PR #43 round-5 review: _known_fields fed EVERY observation
    payload into the allowlist, including document quotes
    (OBS-ESTATE-*, no stats) that the confirmation code refuses to
    treat as data. An invented quote observation naming
    AUTO_MERGE.ALL / CHARTS re-opened the instruction bypass. Only
    data observations — numbered, with stats — contribute fields."""
    events = [ledger_mod.LedgerEvent(
        "E000001", "observation",
        {"obs_id": "OBS-ESTATE-1", "file": "AUTO_MERGE.ALL",
         "field": "CHARTS"})]
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["AUTO_MERGE.ALL.CHARTS"], "master_index": False},
        "ledger:E000012 (Greg Holt, systems)", source_kind="analyst"))
    pkg = specgen.generate_spec(events, store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])

    # Control: a real data observation of the same (file, field) IS
    # estate evidence for the field's existence.
    events = [ledger_mod.LedgerEvent(
        "E000001", "observation",
        {"obs_id": "OBS-0001", "file": "AUTO_MERGE.ALL", "field": "CHARTS",
         "stats": {"rows": 12}})]
    pkg = specgen.generate_spec(events, store, "delphi")
    assert any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])


# -- round-6 review: confirmation attribution ----------------------------------

def test_copied_ref_does_not_confirm_the_added_fact():
    """PR #43 round-6 review (Claude, reproduced): a partial
    profiler-data winner citing the bound ACCT observation, plus an
    analyst winner stating the complete story (true_duplicates
    added) with the SAME observation ref copied onto it, produced
    kind profiler-data + data_confirmed — profiling credit for a
    fact no observation measured. The copied ref confirms the keying
    core for the analyst; true_duplicates takes its confirmation
    from a profiler-data winner stating it, or from the resolution
    itself. Here neither does, so the rule is (analyst, False) —
    exactly what the same ledger earns without the copied ref."""
    events = [
        ledger_mod.LedgerEvent("E000001", "observation", {
            "obs_id": "OBS-1", "file": "REG.TXT", "field": "ACCT",
            "stats": {"rows": 10}}),
        ledger_mod.LedgerEvent("E000002", "binding", {
            "subject": "identity", "predicate": "keying_story",
            "binding": ["REG.TXT", "ACCT"], "evidence_refs": ["OBS-1"]}),
        _layout_event("E000003", "REG", "REG.TXT"),
        ledger_mod.LedgerEvent("E000004", "claim", {
            "subject": "identity", "predicate": "keying_story",
            "value": {"key_fields": ["REG.TXT.ACCT"], "master_index": False},
            "source": "OBS-1 (REG.TXT ACCT distribution)",
            "source_kind": "profiler-data", "evidence_refs": ["OBS-1"]}),
        ledger_mod.LedgerEvent("E000005", "claim", {
            "subject": "identity", "predicate": "keying_story",
            "value": {"key_fields": ["REG.TXT.ACCT"], "master_index": False,
                      "true_duplicates": True},
            "source": "ledger:E000006 (Greg Holt, systems)",
            "source_kind": "analyst", "evidence_refs": ["OBS-1"]}),
        ledger_mod.LedgerEvent("E000006", "resolve", {
            "subject": "identity", "predicate": "keying_story",
            "value": {"key_fields": ["REG.TXT.ACCT"], "master_index": False,
                      "true_duplicates": True},
            "source": "ledger answers", "claimed_by": "Greg Holt, systems",
            "source_kind": "analyst", "evidence_refs": []}),
    ]
    rule = _keying_rule(events)
    assert rule["data_confirmed"] is False
    assert rule["provenance"]["kind"] == "analyst"


def test_profiler_winner_stating_true_duplicates_does_not_confirm():
    """PR #43 round-6 review (Claude): a profiler-data winner stating
    the complete story, true_duplicates included, with its bound ACCT
    observation, made the rule profiler-data + data_confirmed. The ACCT
    observation measures the field, not registration behaviour: the
    rule is unconfirmed and the unearned profiler-data kind is gone."""
    events = [
        ledger_mod.LedgerEvent("E000001", "observation", {
            "obs_id": "OBS-1", "file": "REG.TXT", "field": "ACCT",
            "stats": {"rows": 10}}),
        ledger_mod.LedgerEvent("E000002", "binding", {
            "subject": "identity", "predicate": "keying_story",
            "binding": ["REG.TXT", "ACCT"], "evidence_refs": ["OBS-1"]}),
        _layout_event("E000003", "REG", "REG.TXT"),
        ledger_mod.LedgerEvent("E000004", "claim", {
            "subject": "identity", "predicate": "keying_story",
            "value": {"key_fields": ["REG.TXT.ACCT"], "master_index": False},
            "source": "ledger:E000006 (Greg Holt, systems)",
            "source_kind": "analyst", "evidence_refs": ["OBS-1"]}),
        ledger_mod.LedgerEvent("E000005", "claim", {
            "subject": "identity", "predicate": "keying_story",
            "value": {"key_fields": ["REG.TXT.ACCT"], "master_index": False,
                      "true_duplicates": True},
            "source": "OBS-1 (REG.TXT ACCT distribution)",
            "source_kind": "profiler-data", "evidence_refs": ["OBS-1"]}),
        ledger_mod.LedgerEvent("E000006", "resolve", {
            "subject": "identity", "predicate": "keying_story",
            "value": {"key_fields": ["REG.TXT.ACCT"], "master_index": False,
                      "true_duplicates": True},
            "source": "ledger answers", "claimed_by": "Greg Holt, systems",
            "source_kind": "analyst", "evidence_refs": []}),
    ]
    rule = _keying_rule(events)
    assert rule["data_confirmed"] is False
    assert rule["provenance"]["kind"] == "analyst"


def test_observation_payloads_is_the_shared_map():
    """PR #43 round-6 cleanup (Claude): the observation map is built
    once, in claims, and shared by ledger replay and generation —
    specgen no longer keeps its own copy of the loop (or wrapper
    duplicates of is_data_observation / observation_confirms)."""
    events = _dob_events() + [ledger_mod.LedgerEvent("E000002", "claim", {})]
    assert claims_mod.observation_payloads(events) == {
        "OBS-0009": {"obs_id": "OBS-0009", "file": "REG.TXT", "field": "DOB",
                     "stats": {"shape_rates": {"YYMMDD": 1.0}}}}
    assert not hasattr(specgen, "_observation_payloads")
    assert not hasattr(specgen, "_is_data_observation")
    assert not hasattr(specgen, "_ref_confirms")


# -- round-6 review (Claude): lone resolves, answer-derived layouts, merges ----

def test_lone_resolve_emits_no_rule():
    """PR #43 round-6 review (Claude, reproduced): resolution-only
    subjects entered rule generation, so a single resolve event with
    nothing claimed emitted a keying story (kind and confirmation
    taken from the event's own label) or a codeset handling rule. A
    resolution settles a dispute among claims; alone it states
    nothing."""
    events = [
        ledger_mod.LedgerEvent("E000001", "observation", {
            "obs_id": "OBS-0001", "file": "REG.TXT", "field": "ACCT",
            "stats": {"rows": 10}}),
        ledger_mod.LedgerEvent("E000002", "binding", {
            "subject": "identity", "predicate": "keying_story",
            "binding": ["REG.TXT", "ACCT"], "evidence_refs": ["OBS-0001"]}),
        _layout_event("E000003", "REG", "REG.TXT"),
        _layout_event("E000004", "LAB", "LAB.TXT"),
        ledger_mod.LedgerEvent("E000005", "resolve", {
            "subject": "identity", "predicate": "keying_story",
            "value": {"key_fields": ["REG.TXT.ACCT", "LAB.TXT.ACCT"],
                      "master_index": False, "true_duplicates": True},
            "source": "anything", "source_kind": "profiler-data",
            "evidence_refs": ["OBS-0001"]}),
        ledger_mod.LedgerEvent("E000006", "resolve", {
            "subject": "codeset:x", "predicate": "handling",
            "value": "drop all", "source": "me"}),
    ]
    pkg = specgen.generate_spec(events, claims_mod.ClaimStore.from_ledger(events),
                                "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert not any(r["subject"] == "codeset:x" for r in pkg.spec["rules"])


@pytest.mark.parametrize("with_claim", [False, True])
def test_resolved_merge_policy_is_flagged(with_claim):
    """PR #43 round-6 review (Claude): the merge-policy screen read
    only claimed values, so resolving to auto_merge_all — alone, or
    over a route_to_reconciliation claim — left no trace in
    policy_overrides. The resolved value is screened too, and it
    never becomes a rule."""
    store = claims_mod.ClaimStore()
    if with_claim:
        store.add(claims_mod.Claim("identity", "merge_policy",
                                   "route_to_reconciliation",
                                   "ledger:E000001 (an analyst)",
                                   source_kind="analyst"))
    store.resolve("identity", "merge_policy", "auto_merge_all",
                  "ledger:E000002 (an analyst)", source_kind="analyst")
    pkg = specgen.generate_spec([], store, "delphi")
    overrides = [o for o in pkg.spec["policy_overrides"]
                 if o["predicate"] == "merge_policy"]
    assert overrides and "auto_merge_all" in overrides[0]["claimed_values"]
    assert not any(r["predicate"] == "merge_policy" and r["id"] != "SAFETY-IDENTITY-MERGE"
                   for r in pkg.spec["rules"])


# -- machine evidence only: no layout claim or resolution feeds the allowlist --

_INVENTED = {"path": "AUTO_MERGE.ALL", "layouts": {"X": [{"name": "CHARTS"}]}}


def _invented_layout_store(how):
    store = claims_mod.ClaimStore()
    if how == "lone_resolve":
        store.resolve("file:AUTO_MERGE", "layout_binding", _INVENTED,
                      "DATADICT.TXT errata (estate document)",
                      source_kind="document")
    else:
        source, kind = {
            "dictionary": ("LAYOUTS.DAT v5.0 (estate document)", "dictionary"),
            "document": ("REGISTRATION MANUAL p.4", "document"),
            "unlabelled": ("per the estate layouts", ""),
            "analyst": ("ledger:E000040 (an analyst)", "analyst"),
        }[how.removesuffix("_resolved")]
        store.add(claims_mod.Claim("file:AUTO_MERGE", "layout_binding",
                                   _INVENTED, source, source_kind=kind))
        if how.endswith("_resolved"):
            store.resolve("file:AUTO_MERGE", "layout_binding", _INVENTED,
                          "DATADICT.TXT errata (estate document)",
                          source_kind="document")
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["AUTO_MERGE.ALL.CHARTS"], "master_index": False},
        "ledger:E000042 (an analyst)", source_kind="analyst"))
    return store


@pytest.mark.parametrize("how", [
    "dictionary", "document", "unlabelled", "analyst",
    "dictionary_resolved", "analyst_resolved", "lone_resolve"])
def test_no_layout_claim_or_resolution_feeds_the_allowlist(how):
    """PR #43 rounds 4-6: every round found another way to label an
    invented layout as estate truth (an analyst claim, a self-declared
    dictionary/document kind, a source sentence mentioning the estate,
    a resolution, a lone resolve). The allowlist now takes machine
    evidence only — the profiler's inventory and data observations —
    so none of these validates AUTO_MERGE.ALL.CHARTS, however it is
    labelled or resolved."""
    pkg = specgen.generate_spec([], _invented_layout_store(how), "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story"
               for o in pkg.spec["policy_overrides"])


def test_recorded_inventory_feeds_the_allowlist():
    """Control: the same field validates once the profiler's inventory
    records it — machine evidence of what the export's data holds."""
    pkg = specgen.generate_spec(
        _inventory("AUTO_MERGE.ALL", fields=("CHARTS",)),
        _invented_layout_store("analyst"), "delphi")
    assert any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])


@pytest.mark.parametrize("payload", [
    {}, {"files": "REG.TXT"}, {"files": ["REG.TXT"]},
    {"files": {"REG.TXT": "ACCT"}}, {"files": {"REG.TXT": [7, None, ""]}},
])
def test_malformed_inventory_event_contributes_nothing(payload):
    """A malformed inventory event is ignored, never a crash: one bad
    event cannot stop spec generation for the source."""
    events = [ledger_mod.LedgerEvent("E000001", "inventory", payload)]
    assert specgen.recorded_inventory(events) == {}
    store = claims_mod.ClaimStore()
    store.add(claims_mod.Claim(
        "identity", "keying_story",
        {"key_fields": ["REG.TXT.ACCT"], "master_index": False},
        "ledger:E000042 (an analyst)", source_kind="analyst"))
    pkg = specgen.generate_spec(events, store, "delphi")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])


def test_kind_names_the_first_stating_claim_confirmation_from_any():
    """PR #43 review (Muse, minor): pin the attribution choice. With a
    dictionary claim recorded first and a profiler claim of the same
    keying value citing the bound observation, the rule is kind
    ``dictionary`` (who first stated the fact) and data-confirmed (the
    profiler claim's evidence backs it)."""
    story = {"key_fields": ["REG.TXT.ACCT"], "master_index": False}
    events = [
        ledger_mod.LedgerEvent("E000001", "observation", {
            "obs_id": "OBS-1", "file": "REG.TXT", "field": "ACCT",
            "stats": {"rows": 10}}),
        ledger_mod.LedgerEvent("E000002", "binding", {
            "subject": "identity", "predicate": "keying_story",
            "binding": ["REG.TXT", "ACCT"], "evidence_refs": ["OBS-1"]}),
        ledger_mod.LedgerEvent("E000003", "claim", {
            "subject": "identity", "predicate": "keying_story",
            "value": dict(story), "source": "DATADICT.TXT v4.1",
            "source_kind": "dictionary"}),
        ledger_mod.LedgerEvent("E000004", "claim", {
            "subject": "identity", "predicate": "keying_story",
            "value": dict(story), "source": "OBS-1 (REG.TXT ACCT)",
            "source_kind": "profiler-data", "evidence_refs": ["OBS-1"]}),
    ]
    rule = _keying_rule(events)
    assert rule["provenance"]["kind"] == "dictionary"
    assert rule["data_confirmed"] is True
