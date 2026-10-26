"""Interview tools: private source knowledge is accessed only through service.ask.

Run discovery before the conversion; scoring has a separate entry point.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bridge.interview.claims import ClaimStore
from bridge.interview.coverage import Inventory
from bridge.interview.ledger import append_event, read_events
from bridge.interview.profiler import parse_layouts_dat, profile_export
from bridge.interview.specgen import generate_spec
from testbed.scenarios.briar_service import service


def ask(root: Path, analyst: str, question: str, reason: str) -> dict:
    svc = service(root / "source")
    q = append_event(root / "ledger.jsonl", "question", {"analyst": analyst, "text": question, "why": reason})
    response = svc.ask(analyst, question)
    a = append_event(root / "ledger.jsonl", "answer", {"question_id": q.id, "analyst": analyst, "text": response.get("answer"), "error": response.get("error")})
    return {"question_event": q.id, "answer_event": a.id, **response}


def init(root: Path) -> dict:
    svc = service(root / "source")
    docs = {}
    for name in ["STAFF.TXT", "DATADICT.TXT", "SUPPORT.TXT", "CROSSWALKS.TXT", "LAYOUTS.DAT", "manifest.json"]:
        got = svc.read_estate(name)
        assert "error" not in got, got
        docs[name] = got["text"]
        append_event(root / "ledger.jsonl", "document", got)
    layouts, _ = parse_layouts_dat(docs["LAYOUTS.DAT"])
    report = profile_export(root / "source", layouts)
    (root / "profile_report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    for obs in report["observations"]:
        append_event(root / "ledger.jsonl", "observation", {"obs_id": obs["id"], **{k: v for k, v in obs.items() if k != "id"}})
    inventory = Inventory.from_profile_report(report, ["lab", "medication", "diagnosis", "charge"])
    append_event(root / "ledger.jsonl", "inventory", {"files": inventory.files, "code_sets": inventory.code_sets})
    highlights = {f: {field: stats for field, stats in data["fields"].items() if field in {"DOB", "CHART", "RESULT", "UNIT", "AMOUNT", "TIME", "STATUS", "REV", "TEXT"}} for f, data in report["files"].items()}
    return {"documents": {k: v for k, v in docs.items() if k != "LAYOUTS.DAT"}, "profiles": highlights}


def emit(root: Path):
    events = read_events(root / "ledger.jsonl")
    report = json.loads((root / "profile_report.json").read_text())
    inv = Inventory.from_profile_report(report, ["lab", "medication", "diagnosis", "charge"])
    # value_shape_claims are intentionally not auto-added here: numeric-shaped
    # IDs and status fields are not clinical value measurements. All profiled
    # observations are already ledgered and the interviewer resolves meanings.
    pkg = generate_spec(events, ClaimStore.from_ledger(events), "briar", inventory=inv)
    out = root / "spec"
    out.mkdir(exist_ok=True)
    (out / "spec.json").write_text(pkg.spec_json())
    (out / "profile.py").write_text(pkg.profile_code)
    (out / "reader_binding.json").write_text(json.dumps(pkg.reader_binding, indent=2, sort_keys=True))
    for name, content in pkg.crosswalks.items():
        (out / (name + ".csv")).write_text(content)
    return {"rules": len(pkg.spec["rules"]), "known_unknowns": pkg.spec["known_unknowns"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("action", choices=["init", "ask", "emit"])
    p.add_argument("--analyst")
    p.add_argument("--question")
    p.add_argument("--reason", default="Resolve a delivery convention using evidence.")
    a = p.parse_args()
    result = init(a.root) if a.action == "init" else emit(a.root) if a.action == "emit" else ask(a.root, a.analyst, a.question, a.reason)
    print(json.dumps(result, indent=2))
