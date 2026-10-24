"""One-command end-to-end demo: python -m testbed.demo --out demo_out [--patients 300]

Generates a Halcyon export, runs rehearsal 1 with a simulated analyst answering Bridge's questions
(through the same operations the MCP server exposes), verifies, runs rehearsal 2 reusing the answers,
then a cutover delta against a changed export. Writes demo_out/DEMO_TRANSCRIPT.md.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

from bridge.assistant import BridgeAssistant
from testbed.halcyon.generator import generate
from testbed.simulated_user import SimulatedAnalyst


class Transcript:
    def __init__(self) -> None:
        self.lines: list[str] = ["# Bridge conversion demo", ""]

    def h(self, text: str) -> None:
        self.lines += ["", f"## {text}", ""]
        print(f"\n== {text}")

    def say(self, text: str) -> None:
        self.lines.append(text)
        print(text)

    def table(self, header: list[str], rows: list[list[Any]]) -> None:
        self.lines += ["", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        self.lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
        self.lines.append("")


def converse(a: BridgeAssistant, analyst: SimulatedAnalyst, t: Transcript, max_rounds: int = 40) -> dict[str, Any]:
    """The assistant loop: on every pause, present grouped questions to the analyst, record answers, resume."""
    asked = Counter()
    for _ in range(max_rounds):
        st = a.run_status()
        blocking = a.list_questions(blocking_only=True, limit=500)["questions"]
        if st["status"] != "paused" and not blocking:
            return st
        if st["status"] == "paused":
            t.say(f"- **Paused**: {st['pause_reason']}")
        for q in blocking:
            detail = a.get_question(q["id"])
            example = detail["examples"][0]["source"] if detail["examples"] else None
            opt, value, why = analyst.choose(detail, example)
            res = a.answer_question(q["id"], opt, analyst.name, value=value, rationale=why)
            asked[q["kind"]] += 1
            if "error" in res:
                t.say(f"  - could not answer {q['id']}: {res['error']}")
        t.say(f"  - analyst answered {len(blocking)} grouped question(s) ({', '.join(f'{k}×{n}' for k, n in sorted(Counter(q['kind'] for q in blocking).items()))}); resuming")
        a.resume_run("analyst answered blocking questions", analyst.name)
    return a.run_status()


def summarize(a: BridgeAssistant, t: Transcript) -> dict[str, Any]:
    st = a.run_status()
    rows = []
    for rtype, v in st["by_type"].items():
        c = v["counts"]
        rows.append([rtype, sum(c.values()), c.get("loaded", 0), c.get("superseded", 0), c.get("dropped", 0),
                     c.get("held", 0) + c.get("blocked", 0), c.get("rejected", 0), v["fidelity_mean"]])
    t.table(["Resource", "Source records", "Loaded", "Merged/dup", "Dropped (policy)", "Waiting", "Rejected", "Fidelity"], rows)
    return st


def simple_mutation(src: Path, dst: Path) -> dict[str, Any]:
    """Fallback cutover mutation (T-111 provides a richer one)."""
    shutil.copytree(src, dst)
    con = sqlite3.connect(dst / "halcyon.db")
    deleted = [r[0] for r in con.execute("SELECT DX_ID FROM DX WHERE CODE_TYPE='10' ORDER BY DX_ID LIMIT 3")]
    con.executemany("DELETE FROM DX WHERE DX_ID=?", [(d,) for d in deleted])
    as_of = json.loads((src / "manifest.json").read_text())["asOf"].replace("-", "")
    moved = [r[0] for r in con.execute("SELECT PAT_ID FROM PAT WHERE ADDR LIKE '%^%^%^%^%' ORDER BY PAT_ID LIMIT 5")]
    for i, p in enumerate(moved):
        con.execute("UPDATE PAT SET ADDR=?, LAST_UPD=? WHERE PAT_ID=?", (f"{100 + i} CUTOVER WAY^^SPRINGFIELD^IL^62701", as_of, p))
    con.execute("UPDATE SCHED SET STATUS='C' WHERE STATUS='S' AND APPT_ID IN (SELECT APPT_ID FROM SCHED WHERE STATUS='S' LIMIT 10)")
    con.commit()
    return {"deleted_problems": deleted, "moved_patients": moved}


def main() -> None:
    ap = argparse.ArgumentParser(prog="testbed.demo")
    ap.add_argument("--out", default="demo_out")
    ap.add_argument("--patients", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    t = Transcript()
    t0 = time.time()

    t.h("1. The legacy source: Halcyon Classic (synthetic)")
    gen = generate(out / "exportA", seed=args.seed, patients=args.patients)
    planted = sum(gen["issues"].values())
    t.say(f"Generated {args.patients} people as {gen['counts']['PAT']} facility charts, {sum(v for k, v in gen['counts'].items() if k.isupper())} "
          f"DB rows plus HL7 feeds and CSV extracts, with **{planted} planted data-quality problems** across "
          f"{len(gen['issues'])} kinds (duplicates, ICD-9 codes, unit-less vitals, truncated notes, DST times, ...).")

    t.h("2. Rehearsal 1: convert, pausing for human decisions")
    analyst = SimulatedAnalyst(out / "exportA")
    a1 = BridgeAssistant(str(out / "rehearsal1.db"))
    st = a1.start_run(str(out / "exportA"), batch_size=200)
    t.say(f"Run `{st['run_id']}` started; Bridge maps, loads in batches of 200 and checks metrics after every batch.")
    st = converse(a1, analyst, t)
    t.say(f"Final status: **{st['status']}**.")
    summarize(a1, t)
    loss = a1.loss_report(limit=8)
    t.say("Biggest sources of fidelity loss (from the loss ledger):")
    t.table(["Resource", "Field", "Class", "Records", "Example"], [[l["rtype"], l["field"], l["klass"], l["n"], (l["example"] or "")[:70]] for l in loss])
    v = a1.verify_run()
    t.say(f"End-of-run verification: counts {'OK' if v['counts']['ok'] else 'FAILED'}, read-back mismatch rate "
          f"{v['readback']['mismatch_rate']} on {v['readback']['sampled']} sampled records, clinical sentinels: "
          + ", ".join(f"{c['name']}={'OK' if c['ok'] else 'FAIL'}" for c in v["sentinels"]["checks"]) + ".")
    persons = json.loads((out / "exportA/answer_key/persons.json").read_text())
    nimbus_patients = a1.runner().client.count("Patient")["active"]
    t.say(f"Identity: Nimbus holds **{nimbus_patients} active patients**; the answer key says there are {len(persons)} real people.")

    r = a1.readiness()
    t.say(f"Go-live readiness: **{r['decision']}** (reasons: {', '.join(r['reasons']) or 'none'}).")
    missing = next(c for c in r["checks"] if c["check"] == "fidelity_loss_signed_off")["detail"]["missing"]
    for domain in missing:
        a1.signoff_domain(domain, "user:sim-domain-owner", "reviewed the loss report for this domain")
    r = a1.readiness()
    t.say(f"After domain owners sign off the loss for {len(missing)} resource types: **{r['decision']}**"
          + (f" (warnings: {', '.join(r['warnings'])})" if r["warnings"] else "") + ".")
    from bridge.report import render_html, report_data
    (out / "rehearsal1_report.html").write_text(render_html(report_data(a1.store)), encoding="utf-8")
    t.say("Full run report: `rehearsal1_report.html` (metrics per batch, alerts, loss ledger, questions).")

    t.h("3. Rehearsal 2: same export, answers carried over")
    a2 = BridgeAssistant(str(out / "rehearsal2.db"))
    a2.start_run(str(out / "exportA"), rules_from=str(out / "rehearsal1.db"))
    st2 = converse(a2, analyst, t)
    cmp = a2.compare_runs(str(out / "rehearsal1.db"))
    s = cmp["summary"]
    t.table(["Metric", "Rehearsal 1", "Rehearsal 2"], [[k, v["a"], v["b"]] for k, v in s.items()])
    t.say(f"Rehearsal 2 finished **{st2['status']}** with {s['questions_blocking']['b']} blocking questions "
          f"(rehearsal 1: {s['questions_blocking']['a']}) and {s['pauses']['b']} pauses (rehearsal 1: {s['pauses']['a']}).")

    t.h("4. Cutover: delta load of a changed export into rehearsal 1's Nimbus")
    try:
        from testbed.halcyon import mutate  # T-111
        changes = mutate.mutate(out / "exportA", out / "exportB", seed=args.seed + 1)
    except (ImportError, AttributeError):
        changes = simple_mutation(out / "exportA", out / "exportB")
    a3 = BridgeAssistant(str(out / "cutover.db"))
    a3.start_run(str(out / "exportB"), prior_run_db=str(out / "rehearsal1.db"))
    converse(a3, analyst, t)
    d = a3.delta_summary()["by_type"]
    t.table(["Resource", "Created", "Updated", "Unchanged", "Deleted in source"],
            [[k, v.get("created", 0), v.get("updated", 0), v.get("unchanged", 0), v.get("source_deleted", 0)] for k, v in d.items()])
    dq = [q for q in a3.list_questions(kind="source_deleted")["questions"]]
    for q in dq:
        t.say(f"- Question for the analyst: {q['prompt']} ({q['records_affected']} records) → analyst chooses **retire**.")
        a3.answer_question(q["id"], "retire" if any(o["key"] == "retire" for o in q["options"]) else "keep", analyst.name)
    if dq:
        a3.resume_run("retire records deleted at source", analyst.name)
    t.say(f"Cutover status: **{a3.run_status()['status']}**. Changes applied: {json.dumps({k: len(v) if isinstance(v, list) else v for k, v in changes.items()})}.")

    t.h("5. Where to go from here")
    t.say("Connect an AI assistant to any of these run DBs: "
          f"`claude mcp add bridge -- python -m bridge --run-db {out.resolve() / 'rehearsal1.db'} mcp` and ask e.g. "
          "*\"what did we lose converting allergies?\"* or *\"explain record DX000123\"*.")
    t.say(f"\n_Demo completed in {time.time() - t0:.0f}s._")
    (out / "DEMO_TRANSCRIPT.md").write_text("\n".join(t.lines) + "\n")
    print(f"\nTranscript: {out / 'DEMO_TRANSCRIPT.md'}")


if __name__ == "__main__":
    main()
