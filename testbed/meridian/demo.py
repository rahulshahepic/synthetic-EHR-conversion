"""End-to-end Meridian demo: generate the export, convert it with the profile the Socratic interview
generated, answer Bridge's runtime questions as Harbor Valley's analysts, and grade the result.

  python -m testbed.meridian.demo --out demo_meridian

The analysts here are role-played policies: each answer follows what that analyst said in the
recorded interview (``src/bridge/interview/ledgers/meridian.jsonl``) and what the question itself
shows. Unlike ``testbed/simulated_user.py`` they never read the answer key; the grader does,
afterwards. Questions outside every interviewed analyst's area keep Bridge's default.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bridge.load.client import connect
from bridge.profiles import load_profile
from bridge.reconcile.answers import answer
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore

DENISE = "sim-analyst:Denise Okafor (HIM)"
RAY = "sim-analyst:Ray Castillo (Lab IS)"
PRIYA = "sim-analyst:Priya Natarajan (Pharmacy)"
NICK = {"DANNY": "DANIEL", "MARIE": "MARY", "JIM": "JAMES", "BOB": "ROBERT", "MIKE": "MICHAEL", "LENA": "ELENA"}
HIM_CODING = {  # HIM coders choosing from the code's description shown in the question
    ("retired_icd10", "M54.5"): ("M54.50", "LOW BACK PAIN with no further detail: M54.50 low back pain, unspecified"),
    ("icd9_one_to_many", "311"): ("F32.A", "documented as DEPRESSION only: F32.A depression, unspecified"),
    ("icd9_one_to_many", "715.90"): ("M17.9", "problem text is OA KNEE: M17.9 osteoarthritis of knee"),
}


def _same_person(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
    """Denise's chart review: same address, compatible SSN4 and DOB (a day/month swap is a desk
    error), and the same name up to a nickname or a transposed letter."""
    def name(c: dict[str, Any]) -> tuple[str, str]:
        last, _, rest = c["PAT_NAME"].partition(",")
        first = rest.split()[0] if rest.split() else ""
        return last, NICK.get(first, first)
    swap = a["DOB"][:4] == b["DOB"][:4] and a["DOB"][4:6] == b["DOB"][6:8] and a["DOB"][6:8] == b["DOB"][4:6]
    (la, fa), (lb, fb) = name(a), name(b)
    checks = {"same address": a["ADDR"] == b["ADDR"],
              "SSN4 compatible": a["SSN4"] == b["SSN4"] or not a["SSN4"] or not b["SSN4"],
              "DOB compatible": a["DOB"] == b["DOB"] or swap,
              "name compatible": fa == fb and (la == lb or sorted(la) == sorted(lb))}
    failed = [k for k, ok in checks.items() if not ok]
    return not failed, "chart review: " + (", ".join(checks) if not failed else "differs on " + ", ".join(failed))


def answer_open(store: RunStore, rid: str, log: list[str]) -> int:
    n = 0
    for q in store.questions(rid, "open"):
        kind, key = q["kind"], q["match_key"]
        choice: tuple[str, str, str | None, str] | None = None
        if kind == "identity_match":
            a, b = q["context"]["charts"]
            same, why = _same_person(a, b)
            choice = (DENISE, "same" if same else "different", None, why)
        elif kind == "missing_birth_date":
            choice = (DENISE, "placeholder", None, "01/01/1900 is the desk placeholder; flag for registration follow-up")
        elif kind == "ambiguous_sex_code":
            choice = (DENISE, "unknown", None, "SEX_CD 3 records an X marker on documents, not a gender identity")
        elif kind == "nka_conflict":
            choice = (DENISE, "keep_allergies", None, "nurses add allergies without clearing the NKA flag")
        elif (kind, key) in HIM_CODING:
            opt, why = HIM_CODING[(kind, key)]
            choice = (DENISE, opt, None, why)
        elif kind == "free_text_problem":
            choice = (DENISE, "keep_text", None, "provider-typed text; HIM does not code without documentation")
        elif kind == "missing_discharge":
            choice = (DENISE, "unknown_end", None, "never invent discharge times; HIM works the list")
        elif kind == "missing_subscriber_relationship":
            choice = (DENISE, "age_rule", None, "blank relationship is a desk omission")
        elif kind == "unmapped_lab":
            choice = (RAY, "exclude", None, "send-out scanned reports have no LOINC; they stay in the legacy archive")
        elif kind == "unmapped_medication":
            choice = (PRIYA, "exclude", None, "no single RxNorm concept; list every order for pharmacist med rec")
        if choice is None:
            continue  # outside every interviewed analyst's area: Bridge's default stands
        by, opt, value, why = choice
        answer(store, q["id"], opt, value, by, why)
        log.append(f"- **{kind}** `{key}` -> `{opt}` by {by.split(':', 1)[1]}: {why}")
        n += 1
    return n


def run_demo(out: Path, seed: int = 42, patients: int = 300) -> dict[str, Any]:
    from .generator import generate
    out.mkdir(parents=True, exist_ok=True)
    export = out / "export"
    generate(export, seed=seed, patients=patients)
    db = out / "meridian.db"
    for p in out.glob("meridian*.db"):
        p.unlink()
    store = RunStore(str(db))
    target = f"embedded:{out / 'meridian_nimbus.db'}"
    runner = Runner(store, connect(target), load_profile("meridian"))
    rid = runner.start(str(export), target)
    log: list[str] = []
    for _ in range(20):
        run = store.run(rid)
        # Bridge pauses when a monitor trips; it can also finish a pass with records held on
        # questions that tripped nothing. Either way the analysts answer what is open, then resume.
        held = run["status"] == "completed_with_exceptions"
        log.append(f"\n**{run['status']}:** {run['pause_reason'] or ('records held on open questions' if held else 'nothing waiting')}")
        answered = answer_open(store, rid, log)
        alerts = store.alerts(rid, "open")
        for a in alerts:
            log.append(f"- alert acknowledged after review: {a['message']}")
        if run["status"] != "paused" and not answered:
            break
        runner.resume(rid, f"{answered} answers recorded; alerts reviewed", DENISE)
    from .grade import conversion_checks, interview_scorecard, render_md
    from testbed import scoring
    spec = json.loads((Path(__file__).resolve().parents[2] / "src/bridge/interview/specs/meridian/spec.json").read_text())
    card = interview_scorecard(spec, json.loads((export / "answer_key/estate_discrepancies.json").read_text()))
    md = render_md(card, conversion_checks(export, db.resolve()), scoring.score(export, db))
    (out / "TRANSCRIPT.md").write_text("# Meridian conversion transcript\n" + "\n".join(log) + "\n")
    (out / "GRADE.md").write_text(md)
    return {"status": store.run(rid)["status"], "run_id": rid, "out": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser(prog="testbed.meridian.demo")
    ap.add_argument("--out", default="demo_meridian")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--patients", type=int, default=300)
    a = ap.parse_args()
    print(json.dumps(run_demo(Path(a.out), a.seed, a.patients), indent=1))


if __name__ == "__main__":
    main()
