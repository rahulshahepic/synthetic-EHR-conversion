"""Run-vs-run comparison (rehearsal N vs rehearsal N+1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .runs.store import RunStore


def run_profile(store: RunStore, run_id: str | None = None) -> dict[str, Any]:
    run = store.run(run_id)
    rid = run["id"]
    counts = store.status_counts(rid)
    fid = {r["rtype"]: round(r["f"], 4) for r in store.db.execute(
        "SELECT rtype, AVG(fidelity) f FROM records WHERE run_id=? AND status='loaded' GROUP BY rtype", (rid,))}
    events = list(reversed(store.events(rid, 1_000_000)))
    pauses = sum(1 for e in events if e["kind"] == "status" and (e["detail"] or {}).get("status") == "paused")
    span = (datetime.fromisoformat(events[-1]["at"]) - datetime.fromisoformat(events[0]["at"])).total_seconds() if events else 0
    qs = store.questions(rid, None)
    return {
        "run_id": rid, "source": run["source"], "status": run["status"],
        "elapsed_seconds": round(span, 1), "pauses": pauses, "batches": len(store.batches(rid)),
        "questions_asked": len(qs), "questions_blocking": sum(q["blocking"] for q in qs),
        "rules_imported": sum(1 for r in store.rules(rid) if r["created_by"].startswith("import:")),
        "alerts": len(store.alerts(rid)),
        "by_type": {t: {**c, "fidelity_mean": fid.get(t)} for t, c in counts.items()},
    }


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    scalar = ["elapsed_seconds", "pauses", "batches", "questions_asked", "questions_blocking", "rules_imported", "alerts"]
    types = sorted(set(a["by_type"]) | set(b["by_type"]))
    by_type = {}
    for t in types:
        ta, tb = a["by_type"].get(t, {}), b["by_type"].get(t, {})
        keys = sorted((set(ta) | set(tb)) - {"fidelity_mean"})
        by_type[t] = {k: {"a": ta.get(k, 0), "b": tb.get(k, 0), "delta": tb.get(k, 0) - ta.get(k, 0)} for k in keys}
        fa, fb = ta.get("fidelity_mean"), tb.get("fidelity_mean")
        by_type[t]["fidelity_mean"] = {"a": fa, "b": fb, "delta": round(fb - fa, 4) if fa is not None and fb is not None else None}
    return {"a": a["run_id"], "b": b["run_id"],
            "summary": {k: {"a": a[k], "b": b[k], "delta": round(b[k] - a[k], 1)} for k in scalar},
            "by_type": by_type}
