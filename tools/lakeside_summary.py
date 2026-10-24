"""Convert a Lakeside (second source system) export with the simulated analyst and print a Markdown summary.
Used by the demo workflow; run locally with: python tools/lakeside_summary.py out_dir"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from bridge.assistant import BridgeAssistant
from testbed.halcyon.generator import generate
from testbed.simulated_user import SimulatedAnalyst


def main(out: Path, patients: int = 200) -> None:
    generate(out / "export", seed=7, patients=patients, profile="lakeside")
    a = BridgeAssistant(str(out / "run.db"))
    a.start_run(str(out / "export"))
    analyst = SimulatedAnalyst(out / "export")
    asked: Counter[str] = Counter()
    for _ in range(40):
        qs = a.list_questions(blocking_only=True, limit=500)["questions"]
        if a.run_status()["status"] != "paused" and not qs:
            break
        for q in qs:
            d = a.get_question(q["id"])
            opt, val, why = analyst.choose(d, d["examples"][0]["source"] if d["examples"] else None)
            a.answer_question(q["id"], opt, analyst.name, value=val, rationale=why)
            asked[q["kind"]] += 1
        a.resume_run("analyst answered", analyst.name)
    st = a.run_status()
    v = a.verify_run()
    lines = ["", "## 6. Second source system: Lakeside (metric units, different codes, unknown facilities)", "",
             f"Status **{st['status']}**; blocking questions answered: "
             + (", ".join(f"{k}×{n}" for k, n in sorted(asked.items())) or "none") + ".",
             f"Verification: {'OK' if v['ok'] else 'FAILED'} (read-back mismatch {v['readback']['mismatch_rate']}).", "",
             "| Resource | Loaded | Dropped | Merged/dup | Waiting | Fidelity |", "|---|---|---|---|---|---|"]
    for rtype, info in st["by_type"].items():
        c = info["counts"]
        lines.append(f"| {rtype} | {c.get('loaded', 0)} | {c.get('dropped', 0)} | {c.get('superseded', 0)} | "
                     f"{c.get('held', 0) + c.get('blocked', 0)} | {info['fidelity_mean']} |")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "lakeside_out"))
