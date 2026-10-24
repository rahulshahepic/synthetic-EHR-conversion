"""Run orchestration: stage -> (map -> load -> measure -> monitor) per batch, with pause/resume."""
from __future__ import annotations

import traceback
from time import perf_counter
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
# Match Nimbus' per-request import limit to amortize batch setup and close overhead.
DEFAULT_BATCH_SIZE = 500


class Runner:
    def __init__(self, store: S.RunStore, client: NimbusClient, profile: Any = halcyon_profile):
        self.store, self.client, self.profile = store, client, profile

    # ---------------------------------------------------------------- lifecycle
    def start(self, source: str, target_label: str = "nimbus", batch_size: int = DEFAULT_BATCH_SIZE,
              types: list[str] | None = None, auto_execute: bool = True,
              rules: list[dict[str, Any]] | None = None, prior_run_db: str | None = None) -> str:
        export = HalcyonExport(source)
        as_of = export.manifest.get("asOf") or date.today().isoformat()
        cfg = {"batch_size": batch_size, "as_of": as_of, "types": types or [t for t in LOAD_ORDER if t in MAPPERS]}
        run_id = self.store.create_run(str(source), target_label, cfg)
        self.store.set_status(run_id, "extracting")
        staging_started = perf_counter()
        stage_all(self.store, run_id, export, self.profile)
        self.store.event(run_id, "staging_timing", {"seconds": perf_counter() - staging_started})
        if prior_run_db:
            from ..reconcile.rules_io import load_rules
            from .delta import stage_source_deletions
            rules = (rules or []) + load_rules(prior_run_db)
            stage_source_deletions(self.store, run_id, prior_run_db)
        if rules:
            from ..reconcile.rules_io import import_rules
            import_rules(self.store, run_id, rules)
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
        self.store.release_ready_blocked(run_id)
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
        from ..verify import verify_run
        verification_started = perf_counter()
        report = verify_run(self.store, self.client, run_id)
        self.store.event(run_id, "verification_timing", {"seconds": perf_counter() - verification_started})
        if not report["ok"]:
            self.store.set_status(run_id, "paused", "end-of-run verification failed: see alerts")
            return "paused"
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
        started = perf_counter()
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

        map_seconds = perf_counter() - started
        nimbus_batch = None
        bridge_batch_id = None
        setup_seconds = submit_seconds = close_seconds = persist_seconds = 0.0
        if submit:
            setup_started = perf_counter()
            bridge_batch_id = self.store.create_batch(run_id, rtype, "")
            nimbus_batch = self.client.create_batch(rtype, bridge_batch_id)
            self.store.db.execute("UPDATE batches SET nimbus_batch_id=? WHERE id=?", (nimbus_batch, bridge_batch_id))
            setup_seconds = perf_counter() - setup_started
            submit_started = perf_counter()
            resp = self.client.submit(nimbus_batch, [{"sourceKey": r["source_key"], "resource": p} for r, _, p in submit])
            submit_seconds = perf_counter() - submit_started
            close_started = perf_counter()
            self.client.close(nimbus_batch)
            close_seconds = perf_counter() - close_started
            persist_started = perf_counter()
            self._persist_results(run_id, rtype, submit, resp, bridge_batch_id, results)
            persist_seconds = perf_counter() - persist_started
        else:
            bridge_batch_id = self.store.create_batch(run_id, rtype, "")
        load_seconds = perf_counter() - started - map_seconds
        released = sum(1 for r in recs if r["status"] == S.BLOCKED or (r.get("note") or "").startswith("released by"))
        return self._measure(run_id, rtype, results, bridge_batch_id, nimbus_batch, released,
                             {'map_seconds': map_seconds, 'load_seconds': load_seconds,
                              'target_setup_seconds': setup_seconds, 'target_submit_seconds': submit_seconds,
                              'target_close_seconds': close_seconds, 'persist_seconds': persist_seconds})

    def _persist_results(self, run_id, rtype, submit, resp, bridge_batch_id, results) -> None:
        # Same per-record outcome as _finish, written with a handful of executemany calls per batch.
        updates: list[tuple[str, dict[str, Any]]] = []
        losses: list[tuple[str, list[dict[str, Any]]]] = []
        for (rec, ctx, payload), res in zip(submit, resp):
            if res["status"] in ("accepted", "unchanged"):
                status, extra = S.LOADED, {"target_id": res.get("targetId"), "unchanged": res["status"] == "unchanged",
                                           "operation": res.get("operation")}
            else:
                status, extra = S.REJECTED, {}
            fields, result = self._outcome(run_id, rtype, rec, ctx, status, payload=payload, batch_id=bridge_batch_id,
                                           issues=res.get("issues"), **extra)
            updates.append((rec["source_key"], fields))
            if status == S.LOADED:
                losses.append((rec["source_key"], ctx.losses()))
            results.append(result)
        with self.store.tx():
            self.store.update_records(run_id, rtype, updates)
            self.store.record_losses(run_id, rtype, losses)

    def _measure(self, run_id: str, rtype: str, results: list[dict[str, Any]], bridge_batch_id: str,
                 nimbus_batch: str | None, released: int = 0, timings: dict | None = None) -> bool:
        m = batch_metrics(results)
        m['timings'] = timings or {}
        # records released by answers (or by a parent loading) are not a fair sample for drift baselines
        m["released_share"] = round(released / len(results), 4) if results else 0.0
        samples = {
            "target_reject_rate": [{"source_key": r["source_key"], "issue": (r["issues"] or [{}])[0]} for r in results if r["status"] == S.REJECTED],
            "ref_unresolved": [{"source_key": r["source_key"], "issue": i} for r in results for i in (r["issues"] or []) if i.get("code") == "E_REF_UNRESOLVED"],
            "hold_rate": [{"source_key": r["source_key"], "question": r.get("held_by")} for r in results if r["status"] == S.HELD],
            "drop_rate": [{"source_key": r["source_key"], "reason": next((a["note"] for a in reversed(r["annotations"])
                                                                          if a["klass"] == "dropped"), None)}
                          for r in results if r["status"] == S.DROPPED],
            "fidelity_mean": sorted(({"source_key": r["source_key"], "fidelity": r["fidelity"]} for r in results
                                     if r["status"] == S.LOADED), key=lambda x: x["fidelity"])[:10],
        }
        fired = monitor_rules.evaluate(self.store, run_id, bridge_batch_id, rtype, m, samples)
        self.store.finish_batch(bridge_batch_id, "loaded" if nimbus_batch else "no_writes",
                                {k: m[k] for k in ("attempted", "loaded", "rejected", "held", "blocked", "dropped", "superseded",
                                                   "created", "updated", "unchanged")}, m)
        self.store.event(run_id, "batch", {"batch": bridge_batch_id, "rtype": rtype, "metrics": {k: m[k] for k in (
            "attempted", "loaded", "rejected", "held", "blocked", "fidelity_mean")}, "alerts": [f["rule"] for f in fired]})
        pauses = [f for f in fired if f["severity"] == monitor_rules.PAUSE]
        if pauses:
            self.store.set_status(run_id, "paused", "; ".join(f["message"] for f in pauses))
            return True
        return False

    def _finish(self, run_id: str, rtype: str, rec: dict[str, Any], ctx: MapContext, status: str, *,
                payload: dict[str, Any] | None = None, target_id: str | None = None, batch_id: str | None = None,
                issues: list[dict[str, Any]] | None = None, note: str | None = None, unchanged: bool = False,
                operation: str | None = None) -> dict[str, Any]:
        fields, result = self._outcome(run_id, rtype, rec, ctx, status, payload=payload, target_id=target_id,
                                       batch_id=batch_id, issues=issues, note=note, unchanged=unchanged, operation=operation)
        self.store.update_record(run_id, rtype, rec["source_key"], **fields)
        if status in (S.LOADED, S.DROPPED, S.SUPERSEDED):
            self.store.record_loss(run_id, rtype, rec["source_key"], ctx.losses())
        return result

    def _outcome(self, run_id: str, rtype: str, rec: dict[str, Any], ctx: MapContext, status: str, *,
                 payload: dict[str, Any] | None = None, target_id: str | None = None, batch_id: str | None = None,
                 issues: list[dict[str, Any]] | None = None, note: str | None = None, unchanged: bool = False,
                 operation: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Record columns to write and the result row for metrics."""
        ann = [a.__dict__ for a in ctx.annotations]
        fidelity = ctx.fidelity()
        fields: dict[str, Any] = {"status": status, "annotations": ann, "fidelity": fidelity, "issues": issues,
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
        return fields, {"source_key": rec["source_key"], "status": status, "fidelity": fidelity, "issues": issues,
                        "annotations": ann, "held_by": ctx.held_by, "unchanged": unchanged, "operation": operation}
