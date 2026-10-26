"""Reproduce the owner-requested messy-source rehearsal.

PYTHONPATH=src:. python -m testbed.scenarios.briar --out runs/briar --patients 320

No remote API/model dependencies. Output directories must be fresh.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from testbed.briar.generate import generate
from .briar_discover import discover
from .briar_grade import canonical, grade
from .briar_run import check_replay, execute, native_check, seal, write
from .briar_report import build


def run(out: Path, patients=320, seed=2626, repeat=True):
    if out.exists(): raise ValueError("use a fresh --out directory; existing evidence is never overwritten")
    generate(out / "source", patients, seed)
    discover(out)
    native_check(out)
    execute(out, "corrected")
    if repeat:
        execute(out, "replay", batch_size=37, runtime_interviews=False)
        execute(out, "idempotent", target=out / "corrected_nimbus.db", runtime_interviews=False)
        a = json.loads((out / "corrected_target.json").read_text())
        for label in ("replay", "idempotent"):
            b = json.loads((out / (label + "_target.json")).read_text())
            assert canonical(a) == canonical(b), label + " changed clinical content"
        second = out / "second_population"
        generate(second / "source", max(32, patients // 2), seed + 101)
        shutil.copytree(out / "spec", second / "spec")
        execute(second, "corrected", runtime_interviews=False)
    replay = check_replay(out)
    write(out / "replay_checks.json", replay)
    seal(out)  # output snapshots are frozen before the first scoring read
    grades = [grade(out, "corrected")]
    if repeat:
        grades += [grade(out, x) for x in ("replay", "idempotent")]
        grades.append(grade(out / "second_population", "corrected"))
    assert all(g["ok"] for g in grades), grades
    write(out / "grade_summary.json", grades)
    build(out)
    print(json.dumps({"all_grades_ok": True, "checks": sum(g["checks_total"] for g in grades), "replay": replay}), flush=True)
    return grades


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--patients", type=int, default=320)
    p.add_argument("--seed", type=int, default=2626)
    p.add_argument("--single", action="store_true")
    a = p.parse_args()
    run(a.out, a.patients, a.seed, not a.single)
