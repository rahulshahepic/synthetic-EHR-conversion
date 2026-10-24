"""Monitor rules evaluated after every batch. A PAUSE-severity breach pauses the run."""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from ..runs.store import RunStore

PAUSE, WARN = "pause", "warn"


@dataclass
class Rule:
    name: str
    metric: str
    op: str            # ">" | "<" | "!=" | "drift_up" | "drift_down"
    threshold: float
    severity: str
    min_attempted: int = 1
    description: str = ""


DEFAULT_RULES = [
    Rule("funnel_invariant", "funnel_ok", "!=", 1, PAUSE, description="every attempted record must be accounted for"),
    Rule("ref_unresolved", "ref_unresolved", ">", 0, PAUSE, description="Nimbus could not resolve a reference: ordering or identity bug"),
    Rule("reject_rate", "target_reject_rate", ">", 0.02, PAUSE, 10, "Nimbus rejected more than 2% of submitted records"),
    Rule("hold_rate", "hold_rate", ">", 0.15, PAUSE, 10, "more than 15% of records need a human answer"),
    Rule("fidelity_floor", "fidelity_mean", "<", 0.70, PAUSE, 10, "mean record fidelity below 0.70"),
    Rule("fidelity_warn", "fidelity_mean", "<", 0.85, WARN, 10, "mean record fidelity below 0.85"),
    Rule("code_coverage", "code_coverage", "<", 0.80, WARN, 10, "less than 80% of coded fields mapped to a standard"),
    Rule("reject_drift", "target_reject_rate", "drift_up", 3.0, PAUSE, 10, "reject rate far above this run's baseline"),
    Rule("fidelity_drift", "fidelity_mean", "drift_down", 3.0, PAUSE, 10, "fidelity far below this run's baseline"),
    Rule("hold_drift", "hold_rate", "drift_up", 3.0, WARN, 10, "hold rate far above this run's baseline"),
]

SUGGESTED = {
    "reject_rate": ["inspect sample rejections (explain_record)", "fix mapping or add a rule, then reprocess the batch",
                    "or acknowledge the alert with a raised threshold"],
    "hold_rate": ["answer the open questions (grouped; one answer can release many records)", "then resume"],
    "fidelity_floor": ["review loss_report for the fields driving loss", "add crosswalk entries / rules", "or acknowledge"],
    "ref_unresolved": ["check load order and identity merges", "revert the batch and reprocess"],
    "reject_drift": ["compare this batch's sources with earlier ones (facility, era, code system)"],
    "fidelity_drift": ["compare this batch's sources with earlier ones (facility, era, code system)"],
}

DRIFT_MIN_HISTORY = 3
DRIFT_MIN_DELTA = {"target_reject_rate": 0.02, "fidelity_mean": 0.10, "hold_rate": 0.05}


def _baseline(store: RunStore, run_id: str, rtype: str, metric: str, exclude: str) -> list[float]:
    vals = []
    for b in store.batches(run_id, rtype):
        if b["id"] == exclude or b["status"] != "loaded" or not b["metrics"]:
            continue
        if b["metrics"].get("released_share", 0) > 0.5:
            continue
        v = b["metrics"].get(metric)
        if v is not None and b["metrics"].get("attempted", 0) >= 10:
            vals.append(float(v))
    return vals


def evaluate(store: RunStore, run_id: str, batch_id: str, rtype: str, m: dict[str, Any],
             samples: dict[str, list[Any]], rules: list[Rule] = DEFAULT_RULES) -> list[dict[str, Any]]:
    overrides = store.overrides(run_id)
    fired = []
    for rule in rules:
        value = m.get(rule.metric)
        if value is None or m.get("attempted", 0) < rule.min_attempted:
            continue
        threshold = overrides.get((rule.name, rtype), overrides.get((rule.name, "*"), rule.threshold))
        breached, shown = False, threshold
        if rule.op == ">":
            breached = value > threshold
        elif rule.op == "<":
            breached = value < threshold
        elif rule.op == "!=":
            breached = float(value) != threshold
        elif m.get("released_share", 0) > 0.5:
            continue
        else:
            hist = _baseline(store, run_id, rtype, rule.metric, batch_id)
            if len(hist) >= DRIFT_MIN_HISTORY:
                mu, sd = statistics.mean(hist), statistics.pstdev(hist)
                delta = (value - mu) if rule.op == "drift_up" else (mu - value)
                z = delta / sd if sd > 0 else (float("inf") if delta > 0 else 0)
                breached = z > threshold and delta > DRIFT_MIN_DELTA.get(rule.metric, 0)
                shown = round(mu, 4)
        if not breached:
            continue
        msg = (f"[{rtype}] {rule.description}: {rule.metric}={value} "
               f"({'baseline' if rule.op.startswith('drift') else 'threshold'} {shown})")
        aid = store.add_alert(run_id, batch_id=batch_id, rtype=rtype, rule=rule.name, metric=rule.metric,
                              observed=float(value), threshold=float(shown), severity=rule.severity, message=msg,
                              samples=samples.get(rule.metric, [])[:10], suggested=SUGGESTED.get(rule.name, []))
        fired.append({"id": aid, "rule": rule.name, "severity": rule.severity, "message": msg})
    return fired
