"""Drive a Socratic import interview from the shell, one ledger event at a time.

The interviewer (a person, or an assistant) works the coverage checklist with these commands;
every step lands in the append-only ledger, and ``generate`` turns the ledger into the spec.

  python -m tools.interview estate   --estate DIR --doc MCS2_EXTRACT_GUIDE.TXT
  python -m tools.interview profile  --ledger L --export DIR [--delimited '|,latin-1,.dat'] [--code-values 15]
  python -m tools.interview obs      --ledger L --file PERSON.DAT --field SEX_CD     (show recorded stats)
  python -m tools.interview ask      --ledger L --analyst registration --name "Denise Okafor" \\
                                     --question "..." --answer "..." [--why "checklist C012"]
  python -m tools.interview claim    --ledger L --subject S --predicate P --value JSON --source SRC \\
                                     [--kind analyst|dictionary|profiler-data|interviewer] [--evidence OBS-0001,...]
  python -m tools.interview resolve  --ledger L --subject S --predicate P --value JSON --source SRC [--kind K] [--evidence ...]
  python -m tools.interview checklist --ledger L [--open]
  python -m tools.interview generate --ledger L --source meridian --out DIR

``ask`` records the analyst's answer as given: the analyst is reached only through this command
(a live analyst session, or the stub replaying a recorded ledger) — never by reading a profile.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bridge.interview import claims as claims_mod
from bridge.interview import coverage, ledger as ledger_mod, specgen
from bridge.interview.analysts import EstateReader
from bridge.interview.profiler import profile_export


def _value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _inventory(events: list[ledger_mod.LedgerEvent]) -> coverage.Inventory:
    code_sets: list[str] = []
    for e in events:
        if e.type == "code_sets":
            code_sets = list(e.payload.get("names", []))
    return coverage.Inventory(files=specgen.recorded_inventory(events), code_sets=sorted(code_sets))


def cmd_estate(a: argparse.Namespace) -> None:
    print(EstateReader([a.estate]).read(a.doc))


def cmd_profile(a: argparse.Namespace) -> None:
    delimited = None
    if a.delimited:
        delim, enc, suffix = a.delimited.split(",")
        delimited = {"delimiter": delim, "encoding": enc, "suffix": suffix}
    report = profile_export(a.export, delimited=delimited, code_value_limit=a.code_values)
    inv = coverage.Inventory.from_profile_report(report)
    ledger_mod.append_event(a.ledger, "inventory", {"files": inv.files, "profiler": {
        "delimited": delimited, "code_value_limit": a.code_values}})
    for obs in report["observations"]:
        ledger_mod.append_event(a.ledger, "observation", {"obs_id": obs["id"], "file": obs["file"],
                                                          "field": obs["field"], "stats": obs["stats"]})
    print(f"recorded inventory ({len(inv.files)} files) and {len(report['observations'])} observations")


def cmd_obs(a: argparse.Namespace) -> None:
    for oid, p in claims_mod.observation_payloads(ledger_mod.read_events(a.ledger)).items():
        if p.get("file") == a.file and (not a.field or p.get("field") == a.field):
            print(oid, p["field"], json.dumps(p.get("stats"), sort_keys=True))


def cmd_ask(a: argparse.Namespace) -> None:
    q = ledger_mod.append_event(a.ledger, "question", {"analyst": a.analyst, "name": a.name, "text": a.question,
                                                       "why": a.why})
    ans = ledger_mod.append_event(a.ledger, "answer", {"analyst": a.analyst, "question_id": q.id, "text": a.answer})
    print(q.id, ans.id)


def _claim_payload(a: argparse.Namespace) -> dict[str, Any]:
    p: dict[str, Any] = {"subject": a.subject, "predicate": a.predicate, "value": _value(a.value),
                         "source": a.source, "confidence": a.confidence}
    if a.kind:
        p["source_kind"] = a.kind
    if a.evidence:
        p["evidence_refs"] = a.evidence.split(",")
    return p


def cmd_claim(a: argparse.Namespace) -> None:
    e = ledger_mod.append_event(a.ledger, "claim", _claim_payload(a))
    store = claims_mod.ClaimStore.from_ledger(ledger_mod.read_events(a.ledger))
    d = store.dispute(a.subject, a.predicate)
    print(e.id, "DISPUTE OPEN: " + json.dumps(d.values) if d and not d.resolved else "")


def cmd_resolve(a: argparse.Namespace) -> None:
    p = _claim_payload(a)
    p.pop("confidence")
    if a.by:
        p["claimed_by"] = a.by
    print(ledger_mod.append_event(a.ledger, "resolve", p).id)


def cmd_code_sets(a: argparse.Namespace) -> None:
    print(ledger_mod.append_event(a.ledger, "code_sets", {"names": a.names.split(",")}).id)


def cmd_checklist(a: argparse.Namespace) -> None:
    events = ledger_mod.read_events(a.ledger)
    items = coverage.build_checklist(_inventory(events), claims_mod.ClaimStore.from_ledger(events))
    for i in items:
        if not a.open or i.status != "covered":
            print(f"{i.id} {i.status:9} {i.subject} {i.predicate}" + (f"  <- {i.evidence}" if i.evidence and not a.open else ""))
    print({s: sum(1 for i in items if i.status == s) for s in ("covered", "disputed", "open")}, file=sys.stderr)


def cmd_generate(a: argparse.Namespace) -> None:
    events = ledger_mod.read_events(a.ledger)
    store = claims_mod.ClaimStore.from_ledger(events)
    pkg = specgen.generate_spec(events, store, a.source, inventory=_inventory(events))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.json").write_text(pkg.spec_json())
    (out / "profile.py").write_text(pkg.profile_code)
    (out / "reader_binding.json").write_text(json.dumps(pkg.reader_binding, indent=1, sort_keys=True) + "\n")
    (out / "stub_analysts.json").write_text(json.dumps(stub_analysts(events), indent=1, sort_keys=True) + "\n")
    print(json.dumps({"rules": len(pkg.spec["rules"]), "known_unknowns": len(pkg.spec["known_unknowns"]),
                      "policy_overrides": len(pkg.spec["policy_overrides"]),
                      "flagged_bindings": len(store.flagged_bindings)}, indent=1))


def stub_analysts(events: list[ledger_mod.LedgerEvent]) -> dict[str, Any]:
    """The CI stub for each interviewed analyst: their recorded answers, replayed byte-for-byte."""
    answers = ledger_mod.answers(events)
    out: dict[str, Any] = {}
    for q in ledger_mod.questions(events):
        aid = q.payload["analyst"]
        entry = out.setdefault(aid, {"name": q.payload.get("name", aid), "answers": {}, "blind_spots": [],
                                     "outside_response": "Outside my area."})
        if q.id in answers:
            entry["answers"][q.payload["text"]] = answers[q.id].payload["text"]
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tools.interview")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("estate"); s.add_argument("--estate", required=True); s.add_argument("--doc", required=True)
    s = sub.add_parser("profile"); s.add_argument("--ledger", required=True); s.add_argument("--export", required=True)
    s.add_argument("--delimited"); s.add_argument("--code-values", type=int, default=None)
    s = sub.add_parser("obs"); s.add_argument("--ledger", required=True); s.add_argument("--file", required=True)
    s.add_argument("--field")
    s = sub.add_parser("ask")
    for f in ("ledger", "analyst", "name", "question", "answer"):
        s.add_argument(f"--{f}", required=True)
    s.add_argument("--why", default="coverage checklist")
    for name in ("claim", "resolve"):
        s = sub.add_parser(name)
        for f in ("ledger", "subject", "predicate", "value", "source"):
            s.add_argument(f"--{f}", required=True)
        s.add_argument("--kind"); s.add_argument("--evidence"); s.add_argument("--confidence", type=float, default=0.9)
        s.add_argument("--by")
    s = sub.add_parser("code-sets"); s.add_argument("--ledger", required=True); s.add_argument("--names", required=True)
    s = sub.add_parser("checklist"); s.add_argument("--ledger", required=True); s.add_argument("--open", action="store_true")
    s = sub.add_parser("generate"); s.add_argument("--ledger", required=True); s.add_argument("--source", required=True)
    s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    {"estate": cmd_estate, "profile": cmd_profile, "obs": cmd_obs, "ask": cmd_ask, "claim": cmd_claim,
     "resolve": cmd_resolve, "code-sets": cmd_code_sets, "checklist": cmd_checklist,
     "generate": cmd_generate}[a.cmd](a)


if __name__ == "__main__":
    main()
