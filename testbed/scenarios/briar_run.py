"""Execute the generated staging path and explicit adapter through stock Bridge/Nimbus.

No grading reads here. The separate briar_grade entry point runs only after
target snapshots and outcome files have been written and hashed.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from bridge.interview.analysts import replay_questions
from bridge.interview.claims import ClaimStore
from bridge.interview.coverage import Inventory
from bridge.interview.ledger import read_events
from bridge.interview.profiler import parse_layouts_dat, profile_export
from bridge.interview.specgen import generate_spec
from bridge.load.client import connect
from bridge.mapping.base import MAPPERS
from bridge.readiness import readiness
from bridge.report import render_html, report_data
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore
from bridge.status import run_summary
from bridge.verify import verify_run
from .briar_adapter import TYPES, install
from .briar_interview import ask
from .briar_service import service


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def execute(root: Path, label="rehearsal1", target=None, batch_size=100, runtime_interviews=True):
    start = perf_counter()
    profile, state, original = install(root)
    client = connect("embedded:" + str(target or root / (label + "_nimbus.db")))
    store = RunStore(str(root / (label + ".db")))
    runner = Runner(store, client, profile)
    try:
        rid = runner.start(str(root / "source"), types=TYPES, batch_size=batch_size)
        pauses = []
        for _ in range(100):
            run = store.run(rid)
            if run["status"] != "paused": break
            alerts = store.alerts(rid, "open")
            if any(a["rule"] in {"clinical_sentinel", "count_reconciliation", "readback", "ref_unresolved", "reject_rate"} for a in alerts):
                raise RuntimeError("correctness failure: refusing to acknowledge and continue: " + json.dumps(alerts))
            pauses.append({"reason": run["pause_reason"], "alerts": alerts})
            runner.resume(rid, "Synthetic rehearsal only: retain unresolved records in quarantine and continue other domains; no human approval or threshold override", "simulated:briar-coordinator")
        else: raise RuntimeError("pause loop exceeded 100; no endless blind retries")
        if runtime_interviews:
            owners = {"birth_date": "registration", "local_time": "systems", "unmapped_medication": "pharmacy", "appointment_status": "systems", "credit": "billing", "lab_unit": "lab", "identity_review": "registration"}
            runtime = []
            for q in store.questions(rid):
                kind = q["kind"].removeprefix("briar_")
                got = ask(root, owners.get(kind, "systems"), q["prompt"], "Runtime reconciliation question; no additional source chart is available. An unknown answer must not release a clinical record.")
                runtime.append({"question_id": q["id"], "kind": q["kind"], "affected": q["affected_count"], "response": got, "disposition": "left_open_no_verified_value"})
            write(root / (label + "_runtime_interviews.json"), runtime)
        verification = verify_run(store, client, rid, readback_per_type=100000)
        ready = readiness(store, client, rid)
        snapshot = {rt: sorted(list(client.iter_search(rt)), key=lambda v: v["sourceKey"]) for rt in TYPES}
        summary = run_summary(store, rid)
        records = {rt: [{"source_key": r["source_key"], "status": r["status"], "note": r["note"], "blocked_by": r["blocked_by"], "held_by": r["held_by"]} for r in map(store._rec, store.db.execute("SELECT * FROM records WHERE run_id=? AND rtype=? ORDER BY source_key", (rid, rt)))] for rt in TYPES}
        result = {"label": label, "run_id": rid, "seconds": round(perf_counter() - start, 3), "summary": summary,
                  "verification": verification, "readiness": ready, "pauses": pauses,
                  "physical_rows": len(state["raw"]), "source_rows_accounted": len({(r["file"], r["line"]) for r in state["accounting"]}),
                  "accounting_dispositions": dict(Counter(r["disposition"] for r in state["accounting"])),
                  "target_counts": {rt: len(vals) for rt, vals in snapshot.items()}, "questions": store.questions(rid, None)}
        write(root / (label + "_target.json"), snapshot)
        write(root / (label + "_records.json"), records)
        write(root / (label + "_accounting.json"), state["accounting"])
        write(root / (label + "_results.json"), result)
        (root / (label + "_report.html")).write_text(render_html(report_data(store, rid)))
        print(json.dumps({"label": label, "status": summary["status"], "seconds": result["seconds"], "target_counts": result["target_counts"], "open_questions": summary["open_questions"], "verification": verification["ok"], "readiness": ready["decision"]}), flush=True)
        return result
    finally:
        MAPPERS.update(original)
        store.db.close()
        client.http.close()


def native_check(root):
    _, _, original = install(root)
    store = RunStore(str(root / "native.db"))
    client = connect("embedded:" + str(root / "native_nimbus.db"))
    try:
        p = SimpleNamespace(READER="briar_native", MERGE_POLICY="route_to_reconciliation")
        rid = Runner(store, client, p).start(str(root / "source"))
        result = {"status": store.run(rid)["status"], "counts": store.status_counts(rid),
                  "target_patients": client.count("Patient")["total"], "events": store.events(rid),
                  "leading_note_whitespace_stripped": sum(json.loads(r[0])["TEXT"].startswith("PLAN:") for r in store.db.execute("SELECT source FROM records WHERE run_id=? AND rtype='NOTE'", (rid,)))}
        write(root / "native_result.json", result)
        print(json.dumps({"native": result}), flush=True)
        return result
    finally:
        MAPPERS.update(original)
        store.db.close()
        client.http.close()


def check_replay(root):
    events = read_events(root / "ledger.jsonl")
    report = json.loads((root / "profile_report.json").read_text())
    inv = Inventory.from_profile_report(report, ["lab", "medication", "diagnosis", "charge"])
    pkg = generate_spec(events, ClaimStore.from_ledger(events), "briar", inventory=inv)
    # Runtime Q&A appends ledger events but adds no new verified claims. Compare
    # semantic content; separately replay the frozen discovery ledger byte-for-byte.
    original = json.loads((root / "spec/spec.json").read_text())
    assert pkg.spec["rules"] == original["rules"]
    frozen = read_events(root / "discovery_ledger.jsonl")
    frozen_pkg = generate_spec(frozen, ClaimStore.from_ledger(frozen), "briar", inventory=inv)
    assert frozen_pkg.spec_json() == (root / "spec/spec.json").read_text()
    assert frozen_pkg.profile_code == (root / "spec/profile.py").read_text()
    svc = service(root / "source")
    layouts, _ = parse_layouts_dat(svc.read_estate("LAYOUTS.DAT")["text"])
    reprofile = profile_export(root / "source", layouts)
    assert reprofile == report
    assert replay_questions(events, svc) == []
    return {"analyst_replay_exact": True, "reprofile_exact": True, "rule_replay_exact": True, "frozen_spec_bytes_exact": True}


def seal(root):
    files = [p for p in root.rglob("*") if p.is_file() and "grading" not in p.parts and p.suffix != ".db"]
    write(root / "conversion_sha256.json", {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)})
