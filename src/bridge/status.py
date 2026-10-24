"""Run summaries and record lineage (shared by CLI and MCP server)."""
from __future__ import annotations

from typing import Any

from .runs.store import RunStore


def run_summary(store: RunStore, run_id: str | None = None) -> dict[str, Any]:
    run = store.run(run_id)
    rid = run["id"]
    counts = store.status_counts(rid)
    fid = {r["rtype"]: round(r["f"], 4) for r in store.db.execute(
        "SELECT rtype, AVG(fidelity) f FROM records WHERE run_id=? AND status='loaded' GROUP BY rtype", (rid,))}
    open_q = store.questions(rid, "open")
    return {
        "run_id": rid, "status": run["status"], "pause_reason": run["pause_reason"], "source": run["source"],
        "passes": run["pass_count"], "config": run["config"],
        "by_type": {t: {"counts": counts.get(t, {}), "fidelity_mean": fid.get(t)} for t in run["config"]["types"] if t in counts},
        "open_questions": {"total": len(open_q), "blocking": sum(q["blocking"] for q in open_q),
                           "records_waiting": sum(q["affected_count"] for q in open_q if q["blocking"])},
        "open_alerts": [{k: a[k] for k in ("id", "rtype", "rule", "severity", "message")} for a in store.alerts(rid, "open")],
        "batches": len(store.batches(rid)),
    }


def metrics_view(store: RunStore, run_id: str, rtype: str | None = None, batch_id: str | None = None) -> list[dict[str, Any]]:
    if batch_id:
        b = store.batch(batch_id)
        return [{"batch": b["id"], "rtype": b["rtype"], "status": b["status"], "metrics": b["metrics"]}]
    return [{"batch": b["id"], "rtype": b["rtype"], "status": b["status"],
             "metrics": {k: (b["metrics"] or {}).get(k) for k in (
                 "attempted", "loaded", "rejected", "held", "blocked", "target_reject_rate", "hold_rate",
                 "fidelity_mean", "code_coverage")}}
            for b in store.batches(run_id, rtype)]


def explain(store: RunStore, run_id: str, source_key: str, rtype: str | None = None) -> list[dict[str, Any]]:
    recs = [store.record(run_id, rtype, source_key)] if rtype else store.find_record(run_id, source_key)
    out = []
    for r in recs:
        if not r:
            continue
        out.append({
            "rtype": r["rtype"], "source_key": r["source_key"], "status": r["status"], "note": r["note"],
            "lineage": r["lineage"], "source": r["source"], "mapped": r["mapped"], "fidelity": r["fidelity"],
            "annotations": r["annotations"], "target_issues": r["issues"], "nimbus_id": r["target_id"],
            "batch": r["batch_id"], "held_by": r["held_by"], "blocked_by": r["blocked_by"],
        })
    return out
