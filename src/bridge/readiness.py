"""Go-live readiness: a GO / NO-GO decision with reasons, plus per-domain loss sign-offs by named owners."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .load.client import NimbusClient
from .runs import store as S


def _loss_by_type(store: S.RunStore, run_id: str) -> dict[str, int]:
    return {r["rtype"]: r["n"] for r in store.db.execute(
        "SELECT l.rtype, COUNT(*) n FROM loss l JOIN records r ON r.run_id=l.run_id AND r.rtype=l.rtype "
        "AND r.source_key=l.source_key WHERE l.run_id=? AND r.status IN ('loaded','dropped','superseded') GROUP BY l.rtype",
        (run_id,))}


def signoff(store: S.RunStore, run_id: str, domain: str, by: str, note: str = "") -> dict[str, Any]:
    """A named owner accepts the fidelity loss for one resource type, as it stands now."""
    if not by.startswith("user:"):
        raise ValueError("sign-off must be by a named user ('user:<name>')")
    loss = _loss_by_type(store, run_id).get(domain, 0)
    entry = {"by": by, "note": note, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "loss_records": loss,
             "loss_detail": store.loss_summary(run_id, domain)[:20]}
    store.xset(run_id, "signoff", domain, entry)
    store.event(run_id, "signoff", {"domain": domain, "by": by, "loss_records": loss})
    return {"domain": domain, **entry}


def readiness(store: S.RunStore, client: NimbusClient | None, run_id: str | None = None) -> dict[str, Any]:
    run = store.run(run_id)
    rid = run["id"]
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any, required: bool = True) -> None:
        checks.append({"check": name, "ok": ok, "required": required, "detail": detail})

    check("run_finished", run["status"] in ("completed", "completed_with_exceptions"),
          {"status": run["status"], "reason": run["pause_reason"]})
    open_q = store.questions(rid, "open")
    blocking = [q for q in open_q if q["blocking"]]
    check("no_blocking_questions", not blocking, [{"id": q["id"], "kind": q["kind"], "records": q["affected_count"]} for q in blocking])
    counts = store.status_counts(rid)
    waiting = {t: {k: c.get(k, 0) for k in (S.HELD, S.BLOCKED, S.REJECTED, S.PENDING) if c.get(k)} for t, c in counts.items()}
    waiting = {t: v for t, v in waiting.items() if v}
    check("every_record_resolved", not waiting, waiting)
    alerts = store.alerts(rid)
    unacked = [a for a in alerts if a["severity"] == "pause" and (a["status"] == "open" or not (a["ack_by"] or "").startswith("user:"))]
    check("pause_alerts_acknowledged_by_named_users", not unacked,
          [{"id": a["id"], "rule": a["rule"], "rtype": a["rtype"], "status": a["status"], "ack_by": a["ack_by"]} for a in unacked])
    if client is not None:
        from .verify import verify_run
        v = verify_run(store, client, rid)
        check("verification", v["ok"], {"counts": v["counts"]["ok"], "readback_mismatch_rate": v["readback"]["mismatch_rate"],
                                        "sentinels": {c["name"]: c["ok"] for c in v["sentinels"]["checks"]}})
    loss = _loss_by_type(store, rid)
    signoffs = store.xall(rid, "signoff")
    missing = {t: n for t, n in loss.items() if t not in signoffs}
    stale = {t: {"signed_at_loss": signoffs[t]["loss_records"], "now": n}
             for t, n in loss.items() if t in signoffs and signoffs[t]["loss_records"] != n}
    check("fidelity_loss_signed_off", not missing and not stale, {"missing": missing, "stale": stale,
                                                                  "signed": {t: s["by"] for t, s in signoffs.items()}})
    assistant_answers = [q["id"] for q in store.questions(rid, "answered") if (q["answer"] or {}).get("answered_by") == "assistant"]
    check("assistant_answers_reviewed", not assistant_answers, assistant_answers, required=False)
    nonblocking_open = [q for q in open_q if not q["blocking"]]
    check("non_blocking_questions_reviewed", not nonblocking_open,
          [{"id": q["id"], "kind": q["kind"], "records": q["affected_count"]} for q in nonblocking_open], required=False)
    go = all(c["ok"] for c in checks if c["required"])
    reasons = [c["check"] for c in checks if c["required"] and not c["ok"]]
    warnings = [c["check"] for c in checks if not c["required"] and not c["ok"]]
    store.event(rid, "readiness", {"decision": "GO" if go else "NO-GO", "reasons": reasons, "warnings": warnings})
    return {"run_id": rid, "decision": "GO" if go else "NO-GO", "reasons": reasons, "warnings": warnings, "checks": checks}
