"""Acceptance tests for the PR #42 review fixes.

Each test names the behavior the reviewers required, in executable form —
no assertions on incidental strings or counts of strings. The adversarial
probe suite that drove these fixes is summarized in the PR discussion;
these are its assertions, folded into the repo suite.
"""
from __future__ import annotations

import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from bridge.extract.registry import register_reader
from bridge.interview import ledger as ledger_mod
from bridge.interview import profiler as profiler_mod
from bridge.interview import reader as reader_mod
from bridge.interview import specgen
from bridge.interview.analysts import AnalystService, EstateReader
from bridge.interview.claims import Claim, ClaimStore
from bridge.interview.coverage import Inventory, build_checklist, uncovered
from bridge.interview.scorecard import grade_entry
from bridge.load.client import connect
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "src/bridge/interview/specs"
LEDGERS = ROOT / "src/bridge/interview/ledgers"


@pytest.fixture(scope="module")
def delphi_export(tmp_path_factory):
    from testbed.delphi import generate
    out = tmp_path_factory.mktemp("acceptance-delphi")
    generate(out, seed=42, patients=200)
    return out


@pytest.fixture(scope="module")
def delphi_binding():
    return json.loads((SPECS / "delphi/reader_binding.json").read_text())


# ---------------------------------------------------------------- firewall

def test_grading_ledger_is_unreachable_through_the_estate_firewall():
    """No configured estate root may serve the grading ledger, by any
    path spelling or case variation; real estate documents still serve."""
    grading_name = "estate_discrepancies.json"
    for root in (ROOT / "testbed/halcyon", ROOT / "testbed/halcyon/estate"):
        svc = AnalystService({}, EstateReader([root]))
        served = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root))
            response = svc.read_estate(rel)
            if path.name == grading_name:
                assert "error" in response, f"firewall served {rel} from {root}"
            elif "text" in response:
                served += 1
        assert served > 0, f"walk over {root} served nothing — walk is not real"
        for spelling in (grading_name, grading_name.upper(),
                         f"grading/{grading_name}", f"estate/{grading_name}"):
            assert "error" in svc.read_estate(spelling), (root, spelling)


# ------------------------------------------------------- validated provenance

def test_unrecorded_observation_citation_does_not_confirm():
    """A resolution citing an observation id that no ledger event records
    must not become data-confirmed profiler evidence."""
    store = ClaimStore()
    store.add(Claim("profile", "pivot_year", 50, "DATADICT.TXT v4.1",
                    source_kind="dictionary"))
    store.add(Claim("profile", "pivot_year", 30, "ledger:E000001 (analyst)",
                    source_kind="analyst", evidence_refs=("E000001",)))
    store.resolve("profile", "pivot_year", 30, "OBS-9999 (never recorded)",
                  evidence_refs=("OBS-9999",))
    pkg = specgen.generate_spec([], store, "acceptance")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is False
    assert rule["provenance"]["kind"] == "analyst"


def test_recorded_observation_confirms_the_claim_it_backs():
    """Counterpart: an OBS-<digits> event with real stats in the ledger
    does confirm, and kind stays with whoever claimed the value."""
    store = ClaimStore()
    store.add(Claim("profile", "pivot_year", 50, "DATADICT.TXT v4.1",
                    source_kind="dictionary"))
    store.add(Claim("profile", "pivot_year", 30, "ledger:E000001 (analyst)",
                    source_kind="analyst", evidence_refs=("E000001",)))
    store.resolve("profile", "pivot_year", 30, "OBS-0007 (DOB distribution)",
                  evidence_refs=("OBS-0007",))
    store.bind("profile", ("REG.TXT", "DOB"), evidence_refs=("OBS-0007",))
    events = [ledger_mod.LedgerEvent(
        "E000100", "observation",
        {"obs_id": "OBS-0007", "file": "REG.TXT", "field": "DOB",
         "stats": {"shape_rates": {"YYMMDD": 1.0}}})]
    pkg = specgen.generate_spec(events, store, "acceptance")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is True
    assert rule["provenance"]["kind"] == "analyst"


def test_estate_document_quotes_never_become_profiler_confirmation():
    """The shipped Halcyon spec: its resolutions cite interface-notes
    document quotes (OBS-ESTATE-*), so no rule may be data-confirmed and
    the notes-backed facts must read as dictionary evidence."""
    events = ledger_mod.read_events(LEDGERS / "halcyon.jsonl")
    pkg = specgen.generate_spec(events, ClaimStore.from_ledger(events), "halcyon")
    assert not any(r["data_confirmed"] for r in pkg.spec["rules"])
    tz = next(r for r in pkg.spec["rules"] if r["predicate"] == "facility_tz")
    assert tz["provenance"]["kind"] == "dictionary"
    cents = next(r for r in pkg.spec["rules"] if r["predicate"] == "charge_cents_from")
    assert cents["provenance"]["kind"] == "analyst"


# ------------------------------------------------------------------- claims

def test_fresh_contradiction_reopens_a_resolved_dispute():
    store = ClaimStore()
    store.add(Claim("unit:POT", "unit", "MG/DL", "dictionary"))
    store.add(Claim("unit:POT", "unit", "MEQ/L", "analyst"))
    store.resolve("unit:POT", "unit", "MEQ/L", "OBS-0001")
    store.add(Claim("unit:POT", "unit", "MMOL/L", "second analyst"))
    dispute = store.dispute("unit:POT", "unit")
    assert dispute is not None and not dispute.resolved
    assert store.resolved_value("unit:POT", "unit") is None


def test_corroborating_claim_does_not_reopen_a_resolved_dispute():
    store = ClaimStore()
    store.add(Claim("field:X", "format", "YYMMDD", "dictionary"))
    store.add(Claim("field:X", "format", "MMDDYY", "analyst"))
    store.resolve("field:X", "format", "YYMMDD", "OBS-0001")
    store.add(Claim("field:X", "format", "MMDDYY", "another analyst"))
    store.add(Claim("field:X", "format", "YYMMDD", "profiler"))
    dispute = store.dispute("field:X", "format")
    assert dispute is not None and dispute.resolved
    assert store.resolved_value("field:X", "format") == "YYMMDD"


def test_dispute_resolved_to_none_stays_a_known_unknown():
    store = ClaimStore()
    store.add(Claim("field:REG.FAX", "convention", "text(14)", "dictionary"))
    store.add(Claim("field:REG.FAX", "convention", "free-text(20)", "analyst"))
    store.resolve("field:REG.FAX", "convention", None, "layouts: field absent")
    pkg = specgen.generate_spec([], store, "acceptance")
    assert not any(r["subject"] == "field:REG.FAX" for r in pkg.spec["rules"])
    unknown = next(u for u in pkg.spec["known_unknowns"]
                   if u["subject"] == "field:REG.FAX")
    assert unknown["resolved_value"] is None


def test_identity_claim_under_any_predicate_is_overridden_by_policy():
    store = ClaimStore()
    store.add(Claim("identity", "auto_merge", "never_merge", "analyst"))
    pkg = specgen.generate_spec([], store, "acceptance")
    assert not any(r["value"] == "never_merge" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "auto_merge" for o in pkg.spec["policy_overrides"])
    policy = next(r for r in pkg.spec["rules"] if r["id"] == "SAFETY-IDENTITY-MERGE")
    assert policy["value"] == "route_to_reconciliation"


def test_open_coverage_items_become_known_unknowns():
    """generate_spec consumes the coverage checklist: every open or
    disputed item lands in known_unknowns, never silently dropped."""
    store = ClaimStore()
    inventory = Inventory(files={"REG.TXT": ["DOB", "NAME"]}, code_sets=["payer"])
    open_items = uncovered(build_checklist(inventory, store))
    pkg = specgen.generate_spec([], store, "acceptance", inventory=inventory)
    unknown_keys = {(u["subject"], u["predicate"]) for u in pkg.spec["known_unknowns"]}
    missing = [(i.subject, i.predicate) for i in open_items
               if (i.subject, i.predicate) not in unknown_keys]
    assert not missing


# ---------------------------------------------------------------- scorecard

def test_missing_fact_grades_missed_not_routed():
    verdict = grade_entry({"id": "dict_pivot_year"},
                          {"rules": [], "known_unknowns": []})
    assert verdict["verdict"] == "missed"


def test_missing_fact_negative_control_on_the_real_spec():
    """Deleting both the rule and the unknown for a routed entry must
    flip it to missed — routing requires an explicit artifact."""
    events = ledger_mod.read_events(LEDGERS / "delphi.jsonl")
    pkg = specgen.generate_spec(events, ClaimStore.from_ledger(events), "delphi")
    entry = {"id": "dict_appt_status_incomplete"}
    assert grade_entry(entry, pkg.spec)["verdict"] == "routed-to-runtime-question"
    stripped = {"rules": [r for r in pkg.spec["rules"]
                          if r["subject"] != "field:APPT.TXT.STATUS"],
                "known_unknowns": [u for u in pkg.spec["known_unknowns"]
                                   if u["subject"] != "field:APPT.TXT.STATUS"]}
    assert grade_entry(entry, stripped)["verdict"] == "missed"


# ------------------------------------------------------------- crosswalk CSV

def test_crosswalk_values_are_csv_quoted():
    store = ClaimStore()
    store.add(Claim("codeset:dept", "crosswalk",
                    {"A,B": 'x"y', "C": "line1\nline2"}, "analyst"))
    pkg = specgen.generate_spec([], store, "acceptance")
    rows = list(csv.reader(io.StringIO(pkg.crosswalks["dept"])))
    assert rows[0] == ["source", "target", "provenance"]
    body = {r[0]: r[1] for r in rows[1:]}
    assert body == {"A,B": 'x"y', "C": "line1\nline2"}


# ------------------------------------------------------------------- reader

def test_missing_bound_file_is_an_error(tmp_path):
    binding = {"source": "probe", "files": {
        "REG": {"path": "REG.TXT", "key_field": "ACCT",
                "layouts": {"A": [{"name": "RT", "start": 0, "width": 2, "type": "T"},
                                  {"name": "ACCT", "start": 2, "width": 7, "type": "T"}]}}}}
    with pytest.raises(FileNotFoundError):
        reader_mod.stage_records(reader_mod.FixedWidthExport(tmp_path, binding))


def test_unknown_record_type_is_rejected_with_context(tmp_path):
    (tmp_path / "MIX.TXT").write_bytes(b"P1ABCDEF\nZZ123456\n")
    binding = {"source": "probe", "files": {
        "MIX": {"path": "MIX.TXT", "key_field": "CODE",
                "layouts": {"P1": [{"name": "RT", "start": 0, "width": 2, "type": "T"},
                                   {"name": "CODE", "start": 2, "width": 6, "type": "T"}]}}}}
    with pytest.raises(ValueError, match="unknown record type 'ZZ'"):
        reader_mod.stage_records(reader_mod.FixedWidthExport(tmp_path, binding))


def test_profiler_observes_unknown_record_types_instead_of_guessing(tmp_path):
    (tmp_path / "MIX.TXT").write_bytes(b"01hello \nZZhello \n")
    layouts = {"MIX": {"01": [profiler_mod.FieldLayout("RT", 0, 2),
                              profiler_mod.FieldLayout("VAL", 2, 5)]}}
    report = profiler_mod.profile_export(tmp_path, layouts)
    entry = report["files"]["MIX.TXT"]
    assert entry["unknown_record_types"] == {"ZZ": 1}
    assert entry["records"] == 1


def test_delphi_binding_gives_every_record_a_unique_key(delphi_export, delphi_binding):
    records = reader_mod.stage_records(
        reader_mod.FixedWidthExport(delphi_export, delphi_binding))
    assert records, "no records staged"
    assert all(r["source_key"] for r in records)
    keys = [(r["record_type"], r["source_key"]) for r in records]
    assert len(keys) == len(set(keys))


# ------------------------------------------------------- runner integration

def test_generated_delphi_profile_runs_through_the_runner(delphi_export, tmp_path):
    """The committed generated Delphi profile is runnable as generated:
    the Runner resolves its fixed_width reader from the profile's
    SOURCE_SYSTEM binding and stages persisted records."""
    ns: dict = {}
    exec((SPECS / "delphi/profile.py").read_text(), ns)
    profile = SimpleNamespace(**{k: v for k, v in ns.items() if k.isupper()})
    store = RunStore(str(tmp_path / "runs.db"))
    runner = Runner(store, connect(f"embedded:{tmp_path / 'nimbus.db'}"), profile=profile)
    run_id = runner.start(str(delphi_export))
    counts = store.status_counts(run_id)
    staged = sum(sum(c.values()) for c in counts.values())
    manifest = json.loads((delphi_export / "manifest.json").read_text())
    assert staged == sum(manifest["counts"].values()) > 0


def test_factory_persists_records_into_the_run_store(delphi_export, delphi_binding, tmp_path):
    register_reader("acceptance_delphi", reader_mod.make_factory(delphi_binding))
    from bridge.extract.registry import get_reader
    export, stage_fn = get_reader("acceptance_delphi")(delphi_export)
    store = RunStore(str(tmp_path / "runs.db"))
    run_id = store.create_run(str(delphi_export), "nimbus",
                              {"types": [], "batch_size": 10, "as_of": "2026-09-30"})
    counts = stage_fn(store, run_id, export, SimpleNamespace())
    persisted = sum(sum(c.values()) for c in store.status_counts(run_id).values())
    assert persisted == sum(counts.values()) > 0


def test_zero_record_run_fails_loudly(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "manifest.json").write_text(json.dumps({"counts": {}}))
    binding = {"source": "probe", "files": {
        "REG": {"path": "REG.TXT", "optional": True,
                "layouts": {"A": [{"name": "RT", "start": 0, "width": 2, "type": "T"}]}}}}
    register_reader("acceptance_empty", reader_mod.make_factory(binding))
    profile = SimpleNamespace(READER="acceptance_empty", SOURCE_SYSTEM="probe")
    store = RunStore(str(tmp_path / "runs.db"))
    runner = Runner(store, connect(f"embedded:{tmp_path / 'nimbus.db'}"), profile=profile)
    with pytest.raises(RuntimeError, match="zero records"):
        runner.start(str(empty))
    assert store.run()["status"] == "failed"


def test_generated_merge_policy_prevents_automatic_grouping(tmp_path):
    """Driving the Runner with the generated Halcyon profile: no staged
    Patient may group multiple charts, and no automatic link reasons may
    appear — merges are review candidates for a human."""
    from testbed.halcyon.generator import generate
    out = tmp_path / "halcyon"
    generate(out, patients=200, seed=42)
    ns: dict = {}
    exec((SPECS / "halcyon/profile.py").read_text(), ns)
    profile = SimpleNamespace(**{k: v for k, v in ns.items() if k.isupper()})
    store = RunStore(str(tmp_path / "runs.db"))
    runner = Runner(store, connect(f"embedded:{tmp_path / 'nimbus.db'}"),
                    profile=profile)
    run_id = runner.start(str(out), auto_execute=False)
    grouped = 0
    automatic = 0
    for rec in store.records_by_status(run_id, "pending", "Patient", limit=100000):
        source = rec["source"]
        if len(source["members"]) > 1:
            grouped += 1
        automatic += sum(1 for v in source.get("links", {}).values()
                         if v in ("deterministic", "adt_a40"))
    assert grouped == 0
    assert automatic == 0


# ----------------------------------------------------------------- profiler

def test_profiler_survives_superscript_digits_and_ragged_csv(tmp_path):
    (tmp_path / "weird.csv").write_text(
        "id,when,note\n1,²,superscript\n2,0000,midnight\n3,0100\n4,0200,extra,cells\n",
        encoding="utf-8")
    report = profiler_mod.profile_export(tmp_path)
    entry = report["files"]["weird.csv"]
    assert entry["ragged_rows"] == 2
    when = entry["fields"]["when"]
    # '²' (isdigit() but not ASCII) must not crash shape detection, and
    # "0000" counts as minutes-since-midnight (midnight): 3 of 4 values.
    assert when["shape_rates"]["minutes_since_midnight"] == pytest.approx(0.75)


def test_profiler_value_shape_claim_disputes_the_lab_bench_error_belief(delphi_export):
    """The profiler observes word results in LAB.TXT.RESULT; its
    value-shape claim must collide with the analyst's 'non-numeric means
    bench error, exclude' belief and open a dispute."""
    layouts, _ = profiler_mod.parse_layouts_dat(
        (delphi_export / "LAYOUTS.DAT").read_text())
    report = profiler_mod.profile_export(delphi_export, layouts)
    claims = profiler_mod.value_shape_claims(report)
    result_claims = [c for c in claims if c.subject == "field:LAB.TXT.RESULT"]
    assert result_claims, "profiler emitted no value-shape claim for RESULT"
    claim = result_claims[0]
    assert claim.source_kind == "profiler-data"
    assert claim.evidence_refs == (claim.source,)

    store = ClaimStore()
    store.add(Claim("field:LAB.TXT.RESULT", "convention",
                    "numeric value with optional flag suffix; non-numeric "
                    "values are bench errors and are excluded",
                    "ledger:E000047 (Tom Reyes, laboratory)",
                    source_kind="analyst", evidence_refs=("E000047",)))
    store.add(claim)
    dispute = store.dispute("field:LAB.TXT.RESULT", "convention")
    assert dispute is not None and not dispute.resolved

    events = ledger_mod.read_events(LEDGERS / "delphi.jsonl")
    pkg = specgen.generate_spec(events, ClaimStore.from_ledger(events), "delphi")
    assert any(u["subject"] == "field:LAB.TXT.RESULT"
               for u in pkg.spec["known_unknowns"])


def test_generate_spec_with_profile_report_opens_the_same_dispute(delphi_export):
    """The live path: spec building with a fresh profiler report folds the
    value-shape claims into the store, so the belief is disputed even
    before any claim is recorded in a ledger."""
    layouts, _ = profiler_mod.parse_layouts_dat(
        (delphi_export / "LAYOUTS.DAT").read_text())
    report = profiler_mod.profile_export(delphi_export, layouts)
    store = ClaimStore()
    store.add(Claim("field:LAB.TXT.RESULT", "convention",
                    "numeric value with optional flag suffix; non-numeric "
                    "values are bench errors and are excluded",
                    "ledger:E000047 (Tom Reyes, laboratory)",
                    source_kind="analyst", evidence_refs=("E000047",)))
    pkg = specgen.generate_spec([], store, "acceptance", profile_report=report)
    assert any(u["subject"] == "field:LAB.TXT.RESULT"
               for u in pkg.spec["known_unknowns"])
    # generate_spec stays pure: the caller's store gained no claim.
    assert store.dispute("field:LAB.TXT.RESULT", "convention") is None


# -------------------------------------------- round two: subject-bound data

def _obs(obs_id, file, field, stats=None):
    return ledger_mod.LedgerEvent(
        "E000900", "observation",
        {"obs_id": obs_id, "file": file, "field": field,
         "stats": stats or {"count": 5}})


def test_unrelated_observation_does_not_confirm_a_rule():
    """data_confirmed is subject-bound: a real observation of a different
    field confirms nothing about this rule, however it is cited."""
    events = [_obs("OBS-0001", "NOTE.TXT", "TEXT", {"blank_rate": 0.5})]
    store = ClaimStore()
    store.add(Claim("profile", "pivot_year", 30, "ledger:E000009 (analyst guess)",
                    source_kind="analyst", evidence_refs=("OBS-0001",)))
    rule = next(r for r in specgen.generate_spec(events, store, "acceptance").spec["rules"]
                if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is False


def test_resolution_freetext_observation_mention_does_not_confirm():
    """The resolution path validates structured evidence_refs only: an
    OBS id appearing in the resolution's free-text source — even in a
    sentence saying it does not support the resolution — confirms nothing."""
    events = [_obs("OBS-0001", "REG.TXT", "DOB")]
    store = ClaimStore()
    store.add(Claim("profile", "pivot_year", 50, "DATADICT.TXT v4.1",
                    source_kind="dictionary"))
    store.add(Claim("profile", "pivot_year", 30, "ledger:E000001 (analyst)",
                    source_kind="analyst", evidence_refs=("E000001",)))
    store.resolve("profile", "pivot_year", 30,
                  "analyst insists; OBS-0001 does not support this")
    rule = next(r for r in specgen.generate_spec(events, store, "acceptance").spec["rules"]
                if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is False


def test_no_profiler_evidence_cannot_earn_caught_by_profiling():
    """A claim whose only profiler tie is its free-text source label
    ('profiler unavailable') earns neither the profiler-data kind nor a
    caught-by-profiling grade."""
    store = ClaimStore()
    store.add(Claim("profile", "pivot_year", 30, "profiler unavailable"))
    spec = specgen.generate_spec([], store, "acceptance").spec
    assert spec["rules"][0]["data_confirmed"] is False
    assert grade_entry({"id": "dict_pivot_year"}, spec)["verdict"] != "caught-by-profiling"


def test_self_declared_profiler_kind_without_evidence_is_demoted():
    store = ClaimStore()
    store.add(Claim("profile", "pivot_year", 30, "interface_notes.md",
                    source_kind="profiler-data"))
    rule = specgen.generate_spec([], store, "acceptance").spec["rules"][0]
    assert rule["provenance"]["kind"] != "profiler-data"


def test_keying_story_merge_language_is_flagged_as_policy_override():
    """The keying story may describe keying, but auto-merge language in it
    is overridden and flagged like a merge claim under any predicate."""
    store = ClaimStore()
    store.add(Claim("identity", "keying_story",
                    "auto-merge any two charts sharing SSN4+DOB", "ledger:E3"))
    pkg = specgen.generate_spec([], store, "acceptance")
    assert any(o["predicate"] == "keying_story" for o in pkg.spec["policy_overrides"])
    policy = next(r for r in pkg.spec["rules"] if r["id"] == "SAFETY-IDENTITY-MERGE")
    assert policy["value"] == "route_to_reconciliation"


@pytest.mark.parametrize("text", [
    "link any two charts sharing SSN4+DOB without review",
    "collapse duplicates on SSN4+DOB automatically",
])
def test_keying_story_regex_evading_phrasings_are_flagged(text):
    """T-121 acceptance: the two phrasings that evaded the old
    merge-language regex are now structurally impossible as spec rules —
    a keying story is a structured value (key fields, no action verb),
    so free text is flagged and routed, never carried."""
    store = ClaimStore()
    store.add(Claim("identity", "keying_story", text, "ledger:E3"))
    pkg = specgen.generate_spec([], store, "acceptance")
    assert not any(r["predicate"] == "keying_story" for r in pkg.spec["rules"])
    assert any(o["predicate"] == "keying_story" for o in pkg.spec["policy_overrides"])
    assert ("identity", "keying_story") in {
        (u["subject"], u["predicate"]) for u in pkg.spec["known_unknowns"]}


def test_binding_recorded_in_the_ledger_confirms_a_non_field_subject():
    """T-121 acceptance: the subject-to-field binding travels in the
    ledger itself, as its own ``binding`` event for the subject, so a
    Halcyon-shaped subject — a file/field pair the generator has never
    heard of — is data-confirmed purely from the recorded binding."""
    events = [
        ledger_mod.LedgerEvent(
            "E000001", "observation",
            {"obs_id": "OBS-0003", "file": "DEMOG.TXT", "field": "DOBYR",
             "stats": {"shape_rates": {"YY": 1.0}}}),
        ledger_mod.LedgerEvent(
            "E000002", "binding",
            {"subject": "profile", "binding": ["DEMOG.TXT", "DOBYR"],
             "evidence_refs": ["OBS-0003"]}),
        ledger_mod.LedgerEvent(
            "E000003", "claim",
            {"subject": "profile", "predicate": "pivot_year", "value": 30,
             "source": "ledger:E000001 (analyst)", "source_kind": "analyst",
             "evidence_refs": ["OBS-0003"]}),
    ]
    store = ClaimStore.from_ledger(events)
    pkg = specgen.generate_spec(events, store, "acceptance")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is True


def test_claim_cannot_bind_itself_to_the_observation_it_cites():
    """PR #43 review, finding 1 (the self-confirmation hole): a claim
    used to carry its own subject_field, so any claim could bind itself
    to whatever real observation it cited and earn data_confirmed.
    Bindings now belong to the subject. A claim event that attempts to
    smuggle a binding in its payload is ignored, and even with a proper
    subject binding on record, an observation about a DIFFERENT field
    confirms nothing."""
    events = [
        ledger_mod.LedgerEvent(
            "E000001", "observation",
            {"obs_id": "OBS-0001", "file": "NOTE.TXT", "field": "TEXT",
             "stats": {"shape_rates": {"TEXT": 1.0}}}),
        ledger_mod.LedgerEvent(
            "E000002", "claim",
            {"subject": "profile", "predicate": "pivot_year", "value": 50,
             "source": "ledger:E000001 (analyst)", "source_kind": "analyst",
             "evidence_refs": ["OBS-0001"],
             # Attempted self-binding: no longer read from a claim event.
             "subject_field": ["NOTE.TXT", "TEXT"]}),
    ]
    store = ClaimStore.from_ledger(events)
    pkg = specgen.generate_spec(events, store, "acceptance")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is False

    # With the subject's binding properly recorded (profile = REG.TXT
    # DOB), the same NOTE.TXT.TEXT observation still confirms nothing:
    # it is about a different field than the subject's binding.
    events.append(ledger_mod.LedgerEvent(
        "E000003", "binding",
        {"subject": "profile", "binding": ["REG.TXT", "DOB"],
         "evidence_refs": ["OBS-0001"]}))
    store = ClaimStore.from_ledger(events)
    pkg = specgen.generate_spec(events, store, "acceptance")
    rule = next(r for r in pkg.spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["data_confirmed"] is False


# --------------------------------------------- round two: A40 evidence kept

def test_a40_evidence_survives_in_review_candidates():
    """Under auto_merge=False an A40 pair that also score-matches keeps
    its adt_a40 reason and its 1.0 score: the human reconciler must see
    that the source system already merged those charts."""
    from bridge.mapping.identity import resolve
    pats = [{"PAT_ID": "1", "SSN4": "1234", "PAT_NAME": "SMITH^JOHN",
             "DOB": "19600101", "MRN": "1", "FAC_ID": "F", "SEX": "M", "ADDR": ""},
            {"PAT_ID": "2", "SSN4": "1234", "PAT_NAME": "SMITH^JON",
             "DOB": "19600101", "MRN": "2", "FAC_ID": "F", "SEX": "M", "ADDR": ""}]
    clusters, review, _reasons = resolve(pats, [("1", "2")], auto_merge=False)
    assert clusters == {"1": ["1"], "2": ["2"]}
    assert len(review) == 1
    assert review[0].score == 1.0 and "adt_a40" in review[0].reasons


def test_staged_patient_review_payload_keeps_adt_a40(tmp_path):
    """End to end on the generated Halcyon profile (seed 42, 200 patients):
    at least one staged Patient review candidate carries adt_a40."""
    from testbed.halcyon.generator import generate
    out = tmp_path / "halcyon"
    generate(out, patients=200, seed=42)
    ns: dict = {}
    exec((SPECS / "halcyon/profile.py").read_text(), ns)
    profile = SimpleNamespace(**{k: v for k, v in ns.items() if k.isupper()})
    store = RunStore(str(tmp_path / "runs.db"))
    runner = Runner(store, connect(f"embedded:{tmp_path / 'nimbus.db'}"),
                    profile=profile)
    run_id = runner.start(str(out), auto_execute=False)
    review_items = []
    for rec in store.records_by_status(run_id, "pending", "Patient", limit=100000):
        review_items.extend(rec["source"].get("review", []))
    assert review_items, "no review candidates staged"
    assert any("adt_a40" in item["reasons"] for item in review_items)


# ------------------------------------------ round two: execution preconditions

def test_failed_zero_record_run_cannot_be_executed_to_completion(tmp_path):
    def factory(source):
        return SimpleNamespace(manifest={}), lambda *args: {"REG": 9678}
    register_reader("acceptance_no_persistence", factory)
    store = RunStore(str(tmp_path / "run.db"))
    runner = Runner(store, connect("embedded::memory:"),
                    SimpleNamespace(READER="acceptance_no_persistence"))
    with pytest.raises(RuntimeError, match="zero records"):
        runner.start(str(tmp_path))
    run_id = store.run()["id"]
    assert store.run(run_id)["status"] == "failed"
    with pytest.raises(RuntimeError):
        runner.execute(run_id)
    assert store.run(run_id)["status"] == "failed"
    with pytest.raises(RuntimeError):
        runner.resume(run_id)
    assert store.run(run_id)["status"] == "failed"


def test_staged_source_only_run_refuses_execution_and_stays_staged(
        delphi_export, tmp_path):
    """Executing a generated-profile run that staged source records only
    must refuse and preserve the staged state, not die mid-run leaving
    the run 'running'."""
    ns: dict = {}
    exec((SPECS / "delphi/profile.py").read_text(), ns)
    profile = SimpleNamespace(**{k: v for k, v in ns.items() if k.isupper()})
    store = RunStore(str(tmp_path / "runs.db"))
    runner = Runner(store, connect(f"embedded:{tmp_path / 'nimbus.db'}"), profile=profile)
    run_id = runner.start(str(delphi_export))
    assert store.run(run_id)["status"] == "staged"
    with pytest.raises(RuntimeError, match="source records only"):
        runner.execute(run_id)
    assert store.run(run_id)["status"] == "staged"


# --------------------------------------------- round two: firewall by root

def test_broad_roots_are_refused_at_construction():
    """The firewall must not depend on the caller choosing a narrow root:
    a repository checkout, or the src/docs trees themselves, are refused
    as estate roots, and recorded analyst answers are not estate data."""
    for root in (ROOT, ROOT / "src", ROOT / "docs"):
        with pytest.raises(ValueError, match="not an estate root"):
            EstateReader([root])
    svc = AnalystService({}, EstateReader([ROOT / "testbed" / "halcyon" / "estate"]))
    assert "error" in svc.read_estate("stub_analysts.json")


def test_estate_readme_not_served_and_nul_names_refused():
    """Final-pass review: the estate README was meta-commentary (which
    source wins the graded disputes) sitting inside the served root. It
    moved out (testbed/halcyon/ESTATE.md), so the door must now refuse
    it; and a document name containing a NUL byte must come back as the
    usual refusal dict, not an unhandled ValueError from lstat."""
    svc = AnalystService({}, EstateReader([ROOT / "testbed" / "halcyon" / "estate"]))
    assert "error" in svc.read_estate("README.md")
    assert "error" in svc.read_estate("dictionary_excerpts\x00.md")
    with pytest.raises(PermissionError):
        svc.estate.read("dictionary_excerpts\x00.md")


# ------------------------------------------ round three: kind + root parts

def test_document_quote_observation_does_not_earn_profiler_kind():
    """Round three: presence is not data. A self-declared profiler-data
    claim whose only citation is a document-quote observation
    (OBS-ESTATE-*, empty stats) is demoted like any other unearned kind:
    the tie must run through _ref_confirms, not map membership."""
    events = [ledger_mod.LedgerEvent(
        "E000901", "observation",
        {"obs_id": "OBS-ESTATE-1", "file": "interface_notes.md",
         "field": "", "stats": {}})]
    store = ClaimStore()
    store.add(Claim("profile", "facility_tz", "America/Chicago",
                    "interface notes", source_kind="profiler-data",
                    evidence_refs=("OBS-ESTATE-1",)))
    rule = specgen.generate_spec(events, store, "acceptance").spec["rules"][0]
    assert rule["provenance"]["kind"] == "dictionary"
    assert rule["data_confirmed"] is False


def test_numbered_data_observation_earns_profiler_kind():
    """The other half of the round-three rule: a self-declared
    profiler-data claim citing a real profiler observation (numbered id,
    non-empty stats) keeps its kind — the kind is earned by the data,
    not by the label."""
    events = [_obs("OBS-0007", "REG.TXT", "DOB", {"parse_rate": 1.0})]
    store = ClaimStore()
    store.add(Claim("field:REG.TXT.DOB", "convention", "YYMMDD",
                    "profiler observation", source_kind="profiler-data",
                    evidence_refs=("OBS-0007",)))
    rule = specgen.generate_spec(events, store, "acceptance").spec["rules"][0]
    assert rule["provenance"]["kind"] == "profiler-data"


def test_roots_inside_repository_trees_are_refused():
    """Round three: the root check reads every part of the resolved root
    path, ancestors included — a root inside src/ would otherwise serve
    the generated specs, the prior interview's answer sheet."""
    for root in (ROOT / "src" / "bridge",
                 ROOT / "src" / "bridge" / "interview",
                 SPECS, SPECS / "delphi"):
        with pytest.raises(ValueError, match="not an estate root"):
            EstateReader([root])


def test_generated_spec_files_are_denied_under_any_root(tmp_path):
    """A specs/ part is denied on read, like grading/: even under a
    legitimate estate root, generated specs are never estate documents."""
    estate = tmp_path / "estate"
    (estate / "specs").mkdir(parents=True)
    (estate / "specs" / "spec.json").write_text("{}")
    (estate / "manual.md").write_text("estate manual")
    svc = AnalystService({}, EstateReader([estate]))
    assert "error" in svc.read_estate("specs/spec.json")
    assert "estate manual" in svc.read_estate("manual.md")["text"]


# ------------------------------ round four: resolution route + root scoping

def test_resolution_declaring_profiler_kind_without_data_is_demoted():
    """Round four, route 2: a dispute resolution that merely declares
    source_kind='profiler-data', with no data observation behind it,
    earns neither the kind nor a caught-by-profiling grade. The
    invariant sits where the claim and resolution routes meet:
    profiler-data requires subject-bound data confirmation."""
    store = ClaimStore()
    store.add(Claim("profile", "pivot_year", 50, "DATADICT.TXT v4.1",
                    source_kind="dictionary"))
    store.resolve("profile", "pivot_year", 30, "analyst guess",
                  source_kind="profiler-data")
    spec = specgen.generate_spec([], store, "acceptance").spec
    rule = next(r for r in spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["provenance"]["kind"] != "profiler-data"
    assert rule["data_confirmed"] is False
    assert grade_entry({"id": "dict_pivot_year"}, spec)["verdict"] != \
        "caught-by-profiling"


def test_unconfirmed_profiler_kind_rule_earns_no_profiling_credit():
    """The grader's half of the same invariant: even a spec that somehow
    carries a profiler-data rule with data_confirmed False grades no
    profiling credit for it."""
    spec = {"rules": [{"subject": "profile", "predicate": "pivot_year",
                       "value": 30, "data_confirmed": False,
                       "provenance": {"kind": "profiler-data"}}],
            "known_unknowns": []}
    assert grade_entry({"id": "dict_pivot_year"}, spec)["verdict"] == "swallowed"


def test_estate_under_unrelated_src_directory_is_allowed(tmp_path):
    """Round four: the root check is scoped to the root's own repository.
    A project checked out under an unrelated src/ directory (the
    ~/src/<project> layout) is judged by the parts inside its own repo,
    not by its parent directories' names."""
    clone = tmp_path / "src" / "someclone"
    estate = clone / "halcyon" / "estate"
    estate.mkdir(parents=True)
    (clone / "pyproject.toml").write_text("[project]\nname='x'\n")
    (estate / "manual.md").write_text("estate manual")
    svc = AnalystService({}, EstateReader([estate]))
    assert "estate manual" in svc.read_estate("manual.md")["text"]


def test_copied_estate_tree_without_repo_marker_is_allowed():
    """The reviewer's literal repro: an estate tree copied under a src/
    directory with no repository marker anywhere above it falls back to
    the root's own name and children, and is allowed."""
    import tempfile
    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        estate = Path(td) / "src" / "clone" / "halcyon" / "estate"
        estate.mkdir(parents=True)
        (estate / "manual.md").write_text("estate manual")
        svc = AnalystService({}, EstateReader([estate]))
        assert "estate manual" in svc.read_estate("manual.md")["text"]


def test_repo_scoped_roots_still_refuse_structure(tmp_path):
    """With a repo marker present, structure inside that repo is still
    refused, and an estate inside the same repo is still allowed."""
    repo = tmp_path / "repo"
    (repo / "src" / "bridge").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    with pytest.raises(ValueError, match="not an estate root"):
        EstateReader([repo / "src" / "bridge"])
    estate = repo / "testbed" / "estate"
    estate.mkdir(parents=True)
    (estate / "manual.md").write_text("estate manual")
    svc = AnalystService({}, EstateReader([estate]))
    assert "estate manual" in svc.read_estate("manual.md")["text"]


# ------------------------------ broad audit: injection, identity, origins

def test_reader_claim_value_cannot_inject_into_generated_profile():
    """Broad audit P1, value route: a reader claim whose value is a
    code-shaped string is rejected at generation time — the reader name
    must be a plain identifier, never raw text in the profile module."""
    store = ClaimStore()
    store.add(Claim("profile", "reader",
                    'fixed_width"\nUNEXPECTED_SIDE_EFFECT = True\n#',
                    "attacker-controlled claim"))
    with pytest.raises(ValueError, match="not a permitted identifier"):
        specgen.generate_spec([], store, "acceptance")


def test_source_name_cannot_break_out_of_generated_docstring():
    """Round 6: the source argument is caller-supplied text that lands
    in the generated module's docstring. _comment_text flattens control
    characters but cannot neutralize a triple quote, so the source name
    is validated with the same identifier rule as the reader name."""
    with pytest.raises(ValueError, match="not a permitted identifier"):
        specgen.generate_spec([], ClaimStore(), 'x""";PWNED=True;"""')


def test_profile_values_and_citations_cannot_inject_code():
    """Broad audit P1, both remaining routes: a constant's value is
    rendered as a Python literal, and a provenance citation is flattened
    into one comment line. Executing the generated module must define
    exactly the intended constants and nothing else."""
    payload = 'x"\nUNEXPECTED_SIDE_EFFECT = True\n#'
    store = ClaimStore()
    store.add(Claim("profile", "system_org", payload, "analyst claim"))
    store.add(Claim("profile", "mrn_system", "MRN-9",
                    "ledger:E1\nUNEXPECTED_SIDE_EFFECT = True\n#"))
    pkg = specgen.generate_spec([], store, "acceptance")
    assert "UNEXPECTED_SIDE_EFFECT = True" not in \
        [line.strip() for line in pkg.profile_code.splitlines()]
    ns: dict = {}
    exec(pkg.profile_code, ns)
    assert "UNEXPECTED_SIDE_EFFECT" not in ns
    assert ns["SYSTEM_ORG"] == payload


def test_real_inventory_covers_all_committed_layout_bindings(delphi_export):
    """Broad audit P2: with a real profiler-derived inventory (files
    named as on disk, REG.TXT) and the committed Delphi ledger (layout
    claims under file:REG), every layout checklist item is covered.
    Inventory file identity and layout-claim identity must agree."""
    layouts, _ = profiler_mod.parse_layouts_dat(
        (delphi_export / "LAYOUTS.DAT").read_text())
    report = profiler_mod.profile_export(delphi_export, layouts)
    inventory = Inventory.from_profile_report(report)
    events = ledger_mod.read_events(LEDGERS / "delphi.jsonl")
    store = ClaimStore.from_ledger(events)
    items = [i for i in build_checklist(inventory, store)
             if i.predicate == "layout_binding"]
    assert len(items) == 14
    assert all(i.status == "covered" for i in items), \
        [(i.subject, i.status) for i in items if i.status != "covered"]


def test_ingested_dictionary_rows_keep_dictionary_origin():
    """Broad audit P2: rows ingested through the dictionary-ingestion
    API are dictionary claims. The scorecard must not invent an analyst
    finding for a fact no analyst supplied, whatever the source file is
    named."""
    store = ClaimStore()
    store.ingest_rows([{"subject": "profile", "predicate": "pivot_year",
                        "value": 30}], source="vendor-manual.md")
    spec = specgen.generate_spec([], store, "acceptance").spec
    rule = next(r for r in spec["rules"] if r["predicate"] == "pivot_year")
    assert rule["provenance"]["kind"] == "dictionary"
    assert grade_entry({"id": "dict_pivot_year"}, spec)["verdict"] == \
        "caught-by-documents"


def test_optional_file_with_positive_manifest_count_is_an_error(tmp_path):
    """Broad audit P2: 'optional' permits a missing file only when the
    manifest agrees it carries no records. A positive manifest count
    for a missing optional file is a contradiction and must raise."""
    (tmp_path / "REG.TXT").write_bytes(b"A1234567\n")
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"counts": {"REG": 1, "LAB": 1}}))
    fields = [{"name": "RT", "start": 0, "width": 1, "type": "T"},
              {"name": "ACCT", "start": 1, "width": 7, "type": "T"}]
    binding = {"source": "probe", "files": {
        "REG": {"path": "REG.TXT", "key_field": "ACCT",
                "discriminator": {"start": 0, "width": 1},
                "layouts": {"A": fields}},
        "LAB": {"path": "LAB.TXT", "key_field": "ACCT", "optional": True,
                "discriminator": {"start": 0, "width": 1},
                "layouts": {"A": fields}}}}
    with pytest.raises(ValueError, match="manifest counts 1"):
        reader_mod.stage_records(reader_mod.FixedWidthExport(tmp_path, binding))
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"counts": {"REG": 1, "LAB": 0}}))
    records = reader_mod.stage_records(
        reader_mod.FixedWidthExport(tmp_path, binding))
    assert len(records) == 1 and records[0]["record_type"] == "REG"


# ------------------------------------------------------------------- ledger

def test_ledger_appends_are_unique_under_concurrent_writers(tmp_path):
    path = tmp_path / "ledger.jsonl"

    def append_batch(n):
        for i in range(20):
            ledger_mod.append_event(path, "note", {"batch": n, "i": i})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append_batch, range(4)))
    events = ledger_mod.read_events(path)
    assert len(events) == 80
    assert [e.id for e in events] == [ledger_mod.event_id(i) for i in range(1, 81)]
