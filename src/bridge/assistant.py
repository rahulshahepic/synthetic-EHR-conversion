"""Operations exposed to AI assistants (via MCP) and usable directly from Python.

Every method returns JSON-serializable data. Destructive or clinically significant actions carry
explicit guards: the assistant must relay a named user's decision rather than decide itself.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import status as st
from .load.client import connect
from .reconcile.answers import CLINICAL_KINDS, AnswerError, answer
from .runs.revert import RevertBlocked, revert
from .runs.runner import Runner
from .runs.store import RunStore

DOCS = Path(__file__).resolve().parents[2] / "docs"

WORKFLOW = """Bridge converts a legacy EHR export (Halcyon) into Nimbus in batches. After every batch it measures
quality and may PAUSE. Typical loop:
1. run_status -> if paused, read pause_reason and list_alerts.
2. list_questions -> grouped questions, blocking first, most records affected first.
3. For each question: get_question, explain the choice to the user in plain language (include counts and an
   example from context), let the USER choose, then answer_question(answered_by="user:<their name>").
   You may answer non-blocking, non-clinical questions yourself with answered_by="assistant" (flagged for review).
4. resume_run(note=..., by="user:<name>") once the user agrees (this acknowledges open alerts).
5. Use explain_record and loss_report to answer "what happened to X?" and "what did we lose?".
6. revert is destructive: only with explicit user confirmation, and pass confirm=true and confirmed_by.
"""


def present(q: dict[str, Any]) -> str:
    """Plain-language rendering of a question for a human."""
    lines = [q["prompt"], "", f"Affects {q['records_affected']} record(s)."]
    for ex in q.get("examples", [])[:2]:
        src = {k: v for k, v in (ex.get("source") or {}).items() if not k.startswith("_") and v not in ("", None)}
        lines.append(f"Example {ex['source_key']}: " + ", ".join(f"{k}={v}" for k, v in list(src.items())[:8]))
    lines += ["", "Options:"] + [f"  - {o['key']}: {o['label']}" for o in q["options"]]
    return "\n".join(lines)



class BridgeAssistant:
    def __init__(self, run_db: str):
        self.store = RunStore(run_db)
        self.run_db = run_db
        self._runner: Runner | None = None

    def _rid(self, run_id: str | None) -> str:
        return self.store.run(run_id)["id"]

    def runner(self, run_id: str | None = None) -> Runner:
        if self._runner is None:
            self._runner = Runner(self.store, connect(self.store.run(run_id)["target"]))
        return self._runner

    # ------------------------------------------------------------------ read
    def guide(self) -> dict[str, Any]:
        return {"workflow": WORKFLOW, "docs": sorted(p.stem for p in DOCS.glob("*.md")) if DOCS.exists() else []}

    def next_step(self, run_id: str | None = None) -> dict[str, Any]:
        """What a chat assistant should do next, with the next human question rendered in plain language."""
        st = self.run_status(run_id)
        blocking = self.list_questions(run_id, blocking_only=True, limit=1)
        if blocking["questions"]:
            q = self.get_question(blocking["questions"][0]["id"])
            return {"action": "ask_user", "status": st["status"], "pause_reason": st["pause_reason"],
                    "blocking_questions_left": blocking["total"], "question_id": q["id"],
                    "option_keys": [o["key"] for o in q["options"]],
                    "needs_value": [o["key"] for o in q["options"] if o.get("needs_value")], "present_to_user": present(q)}
        waiting = sum(c["counts"].get("pending", 0) for c in st["by_type"].values())
        if st["status"] == "paused" or waiting:
            why = (f"The run is paused: {st['pause_reason']}" if st["status"] == "paused"
                   else f"{waiting} record(s) released by your answers are waiting to load.")
            return {"action": "resume", "status": st["status"], "pause_reason": st["pause_reason"], "records_waiting": waiting,
                    "present_to_user": f"{why}\nNo questions are waiting. Resume?"}
        if st["status"] in ("completed", "completed_with_exceptions"):
            return {"action": "review", "status": st["status"],
                    "present_to_user": "The conversion finished. Next: show the results (status, loss report), then "
                                       "check go-live readiness and ask domain owners to sign off on fidelity loss."}
        return {"action": "wait", "status": st["status"], "present_to_user": f"Run status: {st['status']}."}

    def run_status(self, run_id: str | None = None) -> dict[str, Any]:
        return st.run_summary(self.store, run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.store.db.execute(
            "SELECT id, source, status, created_at, updated_at FROM runs ORDER BY created_at DESC")]

    def list_alerts(self, run_id: str | None = None, status: str | None = "open") -> list[dict[str, Any]]:
        return self.store.alerts(self._rid(run_id), status)

    def get_metrics(self, run_id: str | None = None, resource_type: str | None = None, batch_id: str | None = None) -> list[dict[str, Any]]:
        return st.metrics_view(self.store, self._rid(run_id), resource_type, batch_id)

    def list_questions(self, run_id: str | None = None, kind: str | None = None, blocking_only: bool = False,
                       status: str = "open", limit: int = 25) -> dict[str, Any]:
        qs = self.store.questions(self._rid(run_id), status or None, kind)
        if blocking_only:
            qs = [q for q in qs if q["blocking"]]
        return {
            "total": len(qs),
            "questions": [{
                "id": q["id"], "kind": q["kind"], "blocking": q["blocking"], "clinical": q["kind"] in CLINICAL_KINDS,
                "records_affected": q["affected_count"], "prompt": q["prompt"],
                "options": q["options"], "default_option": q["default_option"], "status": q["status"],
            } for q in qs[:limit]],
        }

    def get_question(self, question_id: str, max_examples: int = 5) -> dict[str, Any]:
        q = self.store.question(question_id)
        examples = []
        for a in q["affected"][:max_examples]:
            rec = self.store.record(q["run_id"], a["rtype"], a["source_key"])
            if rec:
                examples.append({"rtype": a["rtype"], "source_key": a["source_key"], "status": rec["status"],
                                 "source": rec["source"]})
        return {**{k: q[k] for k in ("id", "run_id", "kind", "match_key", "status", "blocking", "prompt", "options",
                                     "default_option", "context", "answer")},
                "clinical": q["kind"] in CLINICAL_KINDS, "records_affected": len(q["affected"]), "examples": examples}

    def explain_record(self, source_key: str, resource_type: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        return st.explain(self.store, self._rid(run_id), source_key, resource_type)

    def loss_report(self, run_id: str | None = None, resource_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.loss_summary(self._rid(run_id), resource_type)[:limit]

    def list_rules(self, run_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.rules(self._rid(run_id))

    def recent_events(self, run_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.events(self._rid(run_id), limit)

    # ------------------------------------------------------------------ write
    def answer_question(self, question_id: str, option: str, answered_by: str, value: str | None = None,
                        rationale: str = "") -> dict[str, Any]:
        if not answered_by or not (answered_by.startswith("user:") or answered_by == "assistant"):
            return {"error": "answered_by must be 'user:<name>' (relaying the user's choice) or 'assistant'"}
        try:
            return answer(self.store, question_id, option, value, answered_by, rationale)
        except (AnswerError, KeyError) as e:
            return {"error": str(e)}

    def acknowledge_alert(self, alert_id: str, note: str, by: str, new_threshold: float | None = None) -> dict[str, Any]:
        al = self.store.alert(alert_id)
        self.store.ack_alert(alert_id, note, by)
        if new_threshold is not None:
            self.store.set_override(al["run_id"], al["rule"], al["rtype"], new_threshold)
        return self.store.alert(alert_id)

    def start_run(self, source: str, target: str | None = None, batch_size: int = 200,
                  rules_from: str | None = None, prior_run_db: str | None = None) -> dict[str, Any]:
        from .reconcile.rules_io import load_rules
        target = target or (RunStore(prior_run_db).run()["target"] if prior_run_db else
                            f"embedded:{Path(self.run_db).with_name(Path(self.run_db).stem + '_nimbus.db')}")
        runner = Runner(self.store, connect(target))
        self._runner = runner
        rid = runner.start(source, target, batch_size, rules=load_rules(rules_from) if rules_from else None,
                           prior_run_db=prior_run_db)
        return st.run_summary(self.store, rid)

    def resume_run(self, note: str, by: str, run_id: str | None = None) -> dict[str, Any]:
        rid = self._rid(run_id)
        self.runner(rid).resume(rid, note, by)
        return st.run_summary(self.store, rid)

    def pause_run(self, reason: str, by: str, run_id: str | None = None) -> dict[str, Any]:
        rid = self._rid(run_id)
        self.runner(rid).pause(rid, reason, by)
        return st.run_summary(self.store, rid)

    def reprocess(self, run_id: str | None = None, statuses: list[str] | None = None, resource_type: str | None = None) -> dict[str, Any]:
        rid = self._rid(run_id)
        return {"requeued": self.runner(rid).reprocess(rid, tuple(statuses or ["rejected"]), resource_type),
                "next": "call resume_run to process the requeued records"}

    def revert(self, scope: str, confirm: bool, confirmed_by: str, target: str | None = None, cascade: bool = False,
               run_id: str | None = None) -> dict[str, Any]:
        if not confirm or not confirmed_by.startswith("user:"):
            return {"error": "revert deletes data from Nimbus: get explicit user consent, then pass confirm=true and "
                             "confirmed_by='user:<name>'"}
        rid = self._rid(run_id)
        try:
            return revert(self.store, self.runner(rid).client, rid, scope, target, cascade, confirmed_by)
        except RevertBlocked as e:
            return {"error": str(e), "blocking_batches": e.blocking}

    def merge_patients(self, survivor: str, duplicate: str, confirmed_by: str, run_id: str | None = None) -> dict[str, Any]:
        from .reconcile.merge import MergeError, merge_loaded_patients
        if not confirmed_by.startswith("user:"):
            return {"error": "merging patients is an identity decision: the user must confirm (confirmed_by='user:<name>')"}
        rid = self._rid(run_id)
        try:
            return merge_loaded_patients(self.store, self.runner(rid).client, rid, survivor, duplicate, confirmed_by)
        except MergeError as e:
            return {"error": str(e)}

    def delta_summary(self, run_id: str | None = None) -> dict[str, Any]:
        from .runs.delta import delta_summary
        return delta_summary(self.store, run_id)

    def readiness(self, run_id: str | None = None) -> dict[str, Any]:
        from .readiness import readiness
        rid = self._rid(run_id)
        return readiness(self.store, self.runner(rid).client, rid)

    def signoff_domain(self, domain: str, by: str, note: str = "", run_id: str | None = None) -> dict[str, Any]:
        from .readiness import signoff
        try:
            return signoff(self.store, self._rid(run_id), domain, by, note)
        except ValueError as e:
            return {"error": str(e)}

    def compare_runs(self, other_run_db: str, run_id: str | None = None) -> dict[str, Any]:
        from .compare import compare, run_profile
        return compare(run_profile(RunStore(other_run_db)), run_profile(self.store, run_id))

    def verify_run(self, run_id: str | None = None) -> dict[str, Any]:
        from .verify import verify_run
        rid = self._rid(run_id)
        return verify_run(self.store, self.runner(rid).client, rid)

    def retire_rule(self, rule_id: str, by: str) -> dict[str, Any]:
        row = self.store.db.execute("SELECT run_id, kind, match_key FROM rules WHERE id=?", (rule_id,)).fetchone()
        if row is None:
            return {"error": f"rule {rule_id} not found"}
        self.store.retire_rule(rule_id)
        self.store.event(row["run_id"], "rule_retired", {"rule": rule_id, "by": by})
        return {"retired": rule_id, "note": "records already converted keep their values; reprocess to re-ask"}
