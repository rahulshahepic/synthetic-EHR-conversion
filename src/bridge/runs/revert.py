"""Revert loaded data via Nimbus batch rollback, newest batch first."""
from __future__ import annotations

from typing import Any

from ..load.client import NimbusClient, TargetError
from . import store as S


class RevertBlocked(Exception):
    def __init__(self, message: str, blocking: list[str]):
        super().__init__(message)
        self.blocking = blocking


def revert(store: S.RunStore, client: NimbusClient, run_id: str, scope: str, target: str | None = None,
           cascade: bool = False, by: str = "user") -> dict[str, Any]:
    if scope == "batch":
        batches = [store.batch(target)]
    elif scope == "type":
        batches = store.batches(run_id, target, "loaded")
    elif scope == "run":
        batches = store.batches(run_id, status="loaded")
    else:
        raise ValueError("scope must be batch, type or run")
    batches = [b for b in batches if b["status"] == "loaded" and b["nimbus_batch_id"]]
    by_nimbus = {b["nimbus_batch_id"]: b for b in store.batches(run_id)}
    types = sorted({b["rtype"] for b in store.batches(run_id)})
    before = {t: client.count(t)["total"] for t in types}
    prior_status = store.run(run_id)["status"]
    store.set_status(run_id, "reverting", f"{scope} {target or ''} by {by}".strip())
    reverted: list[str] = []
    try:
        for b in sorted(batches, key=lambda x: x["seq"], reverse=True):
            if b["id"] in reverted:
                continue
            try:
                res = client.rollback(b["nimbus_batch_id"], cascade=cascade)
            except TargetError as e:
                if e.status == 409:
                    blocking = [by_nimbus[n]["id"] for n in (e.details or {}).get("blockingBatches", []) if n in by_nimbus]
                    raise RevertBlocked(f"batch {b['id']} has dependents in later batches {blocking}; revert those first "
                                        "or pass cascade=true", blocking) from e
                raise
            for nid in res.get("rolledBack", []):
                rb = by_nimbus.get(nid)
                if rb and rb["id"] not in reverted:
                    _mark_reverted(store, run_id, rb["id"])
                    reverted.append(rb["id"])
    except Exception:
        store.set_status(run_id, "paused", f"revert stopped after {len(reverted)} batches")
        store.event(run_id, "revert_failed", {"scope": scope, "target": target, "reverted": reverted})
        raise
    after = {t: client.count(t)["total"] for t in types}
    final = "reverted" if scope == "run" else ("paused" if prior_status not in ("created", "staged") else prior_status)
    store.set_status(run_id, final, f"reverted {len(reverted)} batches ({scope} {target or ''})".strip())
    summary = {"reverted_batches": reverted, "counts_before": before, "counts_after": after}
    store.event(run_id, "revert", {"scope": scope, "target": target, "by": by, **summary})
    return summary


def _mark_reverted(store: S.RunStore, run_id: str, batch_id: str) -> None:
    from ..reconcile.merge import undo_merge_bookkeeping
    store.set_batch_status(batch_id, "reverted")
    undo_merge_bookkeeping(store, run_id, batch_id)
    store.db.execute(
        "UPDATE records SET status='pending', target_id=NULL, batch_id=NULL, updated_at=? "
        "WHERE run_id=? AND batch_id=? AND status IN ('loaded','rejected')", (S.now(), run_id, batch_id))
