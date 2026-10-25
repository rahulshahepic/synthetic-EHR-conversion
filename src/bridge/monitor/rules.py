"""Monitor rules evaluated after every batch. A PAUSE-severity breach pauses the run."""
from __future__ import annotations

import json
import math
import statistics
import weakref
from dataclasses import dataclass, field
from fractions import Fraction
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
    Rule("drop_rate", "drop_rate", ">", 0.15, PAUSE, 20, "more than 15% of records were dropped (not loaded) by policy"),
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
    "drop_rate": ["inspect dropped records (loss_report, explain_record): are they really out of scope?",
                  "fix the mapping or profile, then reprocess", "or acknowledge with a higher threshold if intended"],
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


@dataclass
class _Baseline:
    """Drift-baseline values for one (run, rtype), kept up to date incrementally.

    _baseline() rescans every earlier batch, which is quadratic over a run (thousands of batches per
    type at 50k patients). This holds the same eligible values plus exact rational sums, so the mean and
    population standard deviation come out bit-for-bit equal to statistics.mean/pstdev on that list.
    """
    version: tuple[int, int]
    cursor: int = 0                                                   # highest batch seq scanned
    open: set[str] = field(default_factory=set)                       # scanned while still unfinished
    values: dict[str, dict[str, float]] = field(default_factory=dict)  # metric -> batch id -> value
    sums: dict[str, list[Any] | None] = field(default_factory=dict)    # metric -> [n, sum x, sum x^2]
    seen: dict[str, dict[str, Any]] = field(default_factory=dict)      # eligible batch id -> metrics

    def add(self, batch_id: str, metrics_json: str | None, status: str) -> None:
        if status != "loaded" or not metrics_json:
            return
        m = json.loads(metrics_json)
        if not m or m.get("released_share", 0) > 0.5 or m.get("attempted", 0) < 10:
            return
        for metric, by_batch in self.values.items():
            if m.get(metric) is not None:
                self._put(metric, by_batch, batch_id, float(m[metric]))
        self.seen[batch_id] = m

    def _put(self, metric: str, by_batch: dict[str, float], batch_id: str, v: float) -> None:
        by_batch[batch_id] = v
        sums = self.sums[metric]
        if sums is not None and math.isfinite(v):
            x = Fraction(v)
            sums[0] += 1
            sums[1] += x
            sums[2] += x * x
        else:
            self.sums[metric] = None  # inf/nan: fall back to the statistics module

    def track(self, metric: str) -> dict[str, float]:
        if metric not in self.values:
            self.values[metric], self.sums[metric] = {}, [0, Fraction(0), Fraction(0)]
            for batch_id, m in self.seen.items():
                if m.get(metric) is not None:
                    self._put(metric, self.values[metric], batch_id, float(m[metric]))
        return self.values[metric]


_BASELINES: "weakref.WeakKeyDictionary[RunStore, dict[tuple[str, str], _Baseline]]" = weakref.WeakKeyDictionary()


def _baseline_stats(store: RunStore, run_id: str, rtype: str, metric: str, exclude: str) -> tuple[int, float, float] | None:
    """(n, mean, pstdev) of _baseline(...), computed incrementally; None if there is no history."""
    # Our own status rewrites (revert) bump batch_epoch; commits by other connections bump data_version.
    version = (store.batch_epoch, store.db.execute("PRAGMA data_version").fetchone()[0])
    per_store = _BASELINES.setdefault(store, {})
    b = per_store.get((run_id, rtype))
    if b is None or b.version != version:
        b = per_store[(run_id, rtype)] = _Baseline(version)
    for batch_id in list(b.open):
        row = store.db.execute("SELECT status, metrics FROM batches WHERE id=?", (batch_id,)).fetchone()
        if row is None or row["status"] != "open":
            b.open.discard(batch_id)
            if row is not None:
                b.add(batch_id, row["metrics"], row["status"])
    for row in store.db.execute("SELECT id, seq, status, metrics FROM batches WHERE run_id=? AND rtype=? AND seq>?"
                                " ORDER BY seq", (run_id, rtype, b.cursor)):
        b.cursor = row["seq"]
        if row["status"] == "open":
            b.open.add(row["id"])
        else:
            b.add(row["id"], row["metrics"], row["status"])
    values = b.track(metric)
    excluded = values.get(exclude)
    n = len(values) - (excluded is not None)
    if n < 1:
        return None
    sums = b.sums[metric]
    if sums is None or (excluded is not None and not math.isfinite(excluded)):
        hist = [v for k, v in values.items() if k != exclude]
        return n, statistics.mean(hist), statistics.pstdev(hist)
    count, sx, sxx = sums
    if excluded is not None:
        x = Fraction(excluded)
        count, sx, sxx = count - 1, sx - x, sxx - x * x
    # Same exact formulas as statistics.mean / statistics.pstdev (statistics._ss) for float data.
    mss = (count * sxx - sx * sx) / count / count
    return n, float(sx / count), statistics._float_sqrt_of_frac(mss.numerator, mss.denominator)


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
            stats = _baseline_stats(store, run_id, rtype, rule.metric, batch_id)
            if stats is not None and stats[0] >= DRIFT_MIN_HISTORY:
                _, mu, sd = stats
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
