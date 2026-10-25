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
