"""Run orchestration: stage -> (map -> load -> measure -> monitor) per batch, with pause/resume."""
from __future__ import annotations

import traceback
from datetime import date
from typing import Any

from ..extract.halcyon import HalcyonExport, stage_all
from ..load.client import NimbusClient
from ..mapping import clinical, core  # noqa: F401  (registers mappers)
from ..mapping.base import MAPPERS, MapContext, run_mapper
from ..monitor import rules as monitor_rules
from ..monitor.metrics import batch_metrics
from ..profiles import halcyon as halcyon_profile
from . import store as S

LOAD_ORDER = [
    "Organization", "Location", "Practitioner", "Payer", "Plan", "Patient", "Coverage", "Encounter",
    "Condition", "AllergyIntolerance", "MedicationRequest", "Observation", "Immunization",
    "DocumentReference", "Appointment", "ChargeItem", "UserAccount",
]
DEFAULT_BATCH_SIZE = 200


class Runner:
    def __init__(self, store: S.RunStore, client: NimbusClient, profile: Any = halcyon_profile):
        self.store, self.client, self.profile = store, client, profile

    # ---------------------------------------------------------------- lifecycle
    def start(self, source: str, target_label: str = "nimbus", batch_size: int = DEFAULT_BATCH_SIZE,
              types: list[str] | None = None, auto_execute: bool = True) -> str:
        export = HalcyonExport(source)
        as_of = export.manifest.get("asOf") or date.today().isoformat()
        cfg = {"batch_size": batch_size, "as_of": as_of, "types": types or [t for t in LOAD_ORDER if t in MAPPERS]}
        run_id = self.store.create_run(str(source), target_label, cfg)
        self.store.set_status(run_id, "extracting")
        stage_all(self.store, run_id, export, self.profile)
        self.store.set_status(run_id, "staged")
        if auto_execute:
            self.execute(run_id)
        return run_id

    def execute(self, run_id: str) -> str:
        run = self.store.run(run_id)
        if run["status"] in ("reverting", "reverted", "aborted"):
            raise RuntimeError(f"run is {run['status']}")
        self.store.set_status(run_id, "running")
        self.store.bump_pass(run_id)
        types = run["config"]["types"]
        size = run["config"]["batch_size"]
        progress = True
        while progress:
            progress = False
            for rtype in types:
                while True:
                    queue = self.store.work_queue(run_id, rtype, size)
                    if not queue:
                        break
                    progress = True
                    paused = self.process_batch(run_id, rtype, queue)
                    if paused:
                        return "paused"
        counts = self.store.status_counts(run_id)
        outstanding = sum(c.get(S.HELD, 0) + c.get(S.BLOCKED, 0) + c.get(S.REJECTED, 0) for c in counts.values())
        status = "completed" if not outstanding else "completed_with_exceptions"
        self.store.set_status(run_id, status)
        return status

    def resume(self, run_id: str, note: str = "resumed", by: str = "user") -> str:
        for a in self.store.alerts(run_id, "open"):
            self.store.ack_alert(a["id"], note, by)
        self.store.event(run_id, "resume", {"by": by, "note": note})
        return self.execute(run_id)

    def pause(self, run_id: str, reason: str, by: str = "user") -> None:
        self.store.set_status(run_id, "paused", f"{reason} (by {by})")

    def reprocess(self, run_id: str, statuses: tuple[str, ...] = (S.REJECTED,), rtype: str | None = None) -> int:
        n = 0
        for st in statuses:
            for rec in self.store.records_by_status(run_id, st, rtype, limit=1_000_000):
                self.store.update_record(run_id, rec["rtype"], rec["source_key"], status=S.PENDING, held_by=None, blocked_by=None)
                n += 1
        self.store.event(run_id, "reprocess", {"statuses": statuses, "rtype": rtype, "records": n})
        return n

    # ---------------------------------------------------------------- one batch
    def process_batch(self, run_id: str, rtype: str, recs: list[dict[str, Any]]) -> bool:
        results: list[dict[str, Any]] = []
        submit: list[tuple[dict[str, Any], MapContext, dict[str, Any]]] = []
        with self.store.tx():
            for rec in recs:
                ctx = MapContext(self.store, run_id, rtype, rec, self.profile)
                try:
                    outcome = run_mapper(ctx)
                except Exception as exc:  # a mapper bug must surface as a rejection, not vanish
                    results.append(self._finish(run_id, rtype, rec, ctx, S.REJECTED, issues=[{
                        "code": "BRIDGE_MAPPER_ERROR", "message": f"{type(exc).__name__}: {exc}", "severity": "error",
                        "trace": traceback.format_exc(limit=3)}]))
                    continue
                if outcome.status == "ok":
                    submit.append((rec, ctx, outcome.payload))
                else:
                    status = {"held": S.HELD, "blocked": S.BLOCKED, "dropped": S.DROPPED, "superseded": S.SUPERSEDED}[outcome.status]
                    results.append(self._finish(run_id, rtype, rec, ctx, status, note=outcome.note))

        nimbus_batch = None
        bridge_batch_id = None
        if submit:
            bridge_batch_id = self.store.create_batch(run_id, rtype, "")
            nimbus_batch = self.client.create_batch(rtype, bridge_batch_id)
            self.store.db.execute("UPDATE batches SET nimbus_batch_id=? WHERE id=?", (nimbus_batch, bridge_batch_id))
            resp = self.client.submit(nimbus_batch, [{"sourceKey": r["source_key"], "resource": p} for r, _, p in submit])
            self.client.close(nimbus_batch)
            self._persist_results(run_id, rtype, submit, resp, bridge_batch_id, results)
        else:
            bridge_batch_id = self.store.create_batch(run_id, rtype, "")
        return self._measure(run_id, rtype, results, bridge_batch_id, nimbus_batch)

    def _persist_results(self, run_id, rtype, submit, resp, bridge_batch_id, results) -> None:
        with self.store.tx():
            for (rec, ctx, payload), res in zip(submit, resp):
                if res["status"] in ("accepted", "unchanged"):
                    results.append(self._finish(run_id, rtype, rec, ctx, S.LOADED, payload=payload, target_id=res.get("targetId"),
                                                batch_id=bridge_batch_id, issues=res.get("issues"), unchanged=res["status"] == "unchanged"))
                else:
                    results.append(self._finish(run_id, rtype, rec, ctx, S.REJECTED, payload=payload, issues=res.get("issues"),
                                                batch_id=bridge_batch_id))

    def _measure(self, run_id: str, rtype: str, results: list[dict[str, Any]], bridge_batch_id: str,
                 nimbus_batch: str | None) -> bool:
        m = batch_metrics(results)
        samples = {
            "target_reject_rate": [{"source_key": r["source_key"], "issue": (r["issues"] or [{}])[0]} for r in results if r["status"] == S.REJECTED],
            "ref_unresolved": [{"source_key": r["source_key"], "issue": i} for r in results for i in (r["issues"] or []) if i.get("code") == "E_REF_UNRESOLVED"],
            "hold_rate": [{"source_key": r["source_key"], "question": r.get("held_by")} for r in results if r["status"] == S.HELD],
            "fidelity_mean": sorted(({"source_key": r["source_key"], "fidelity": r["fidelity"]} for r in results
                                     if r["status"] == S.LOADED), key=lambda x: x["fidelity"])[:10],
        }
        fired = monitor_rules.evaluate(self.store, run_id, bridge_batch_id, rtype, m, samples)
        self.store.finish_batch(bridge_batch_id, "loaded" if nimbus_batch else "no_writes",
                                {k: m[k] for k in ("attempted", "loaded", "rejected", "held", "blocked", "dropped", "superseded")}, m)
        self.store.event(run_id, "batch", {"batch": bridge_batch_id, "rtype": rtype, "metrics": {k: m[k] for k in (
            "attempted", "loaded", "rejected", "held", "blocked", "fidelity_mean")}, "alerts": [f["rule"] for f in fired]})
        pauses = [f for f in fired if f["severity"] == monitor_rules.PAUSE]
        if pauses:
            self.store.set_status(run_id, "paused", "; ".join(f["message"] for f in pauses))
            return True
        return False

    def _finish(self, run_id: str, rtype: str, rec: dict[str, Any], ctx: MapContext, status: str, *,
                payload: dict[str, Any] | None = None, target_id: str | None = None, batch_id: str | None = None,
                issues: list[dict[str, Any]] | None = None, note: str | None = None, unchanged: bool = False) -> dict[str, Any]:
        ann = [a.__dict__ for a in ctx.annotations]
        fields: dict[str, Any] = {"status": status, "annotations": ann, "fidelity": ctx.fidelity(), "issues": issues,
                                  "held_by": ctx.held_by if status == S.HELD else None,
                                  "blocked_by": ctx.blocked_by if status == S.BLOCKED else None, "note": note}
        if payload is not None:
            fields["mapped"] = payload
        if status == S.LOADED:
            fields.update(target_id=target_id, batch_id=batch_id)
        elif status == S.REJECTED and batch_id:
            fields["batch_id"] = batch_id
        if status == S.SUPERSEDED and ctx.superseded_by:
            self.store.xset(run_id, "superseded", f"{rtype}/{rec['source_key']}", ctx.superseded_by)
        self.store.update_record(run_id, rtype, rec["source_key"], **fields)
        if status in (S.LOADED, S.DROPPED, S.SUPERSEDED):
            self.store.record_loss(run_id, rtype, rec["source_key"], ctx.losses())
        return {"source_key": rec["source_key"], "status": status, "fidelity": ctx.fidelity(), "issues": issues,
                "annotations": ann, "held_by": ctx.held_by, "unchanged": unchanged}
