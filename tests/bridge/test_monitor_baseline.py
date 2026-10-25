"""The incremental drift baseline must equal the full rescan (statistics.mean/pstdev) bit for bit."""
import random
import sqlite3
import statistics

import pytest

from bridge.monitor import rules
from bridge.runs.store import RunStore

METRICS = ("target_reject_rate", "fidelity_mean", "hold_rate")


def _expected(store, run, rtype, metric, exclude):
    hist = rules._baseline(store, run, rtype, metric, exclude)
    return (len(hist), statistics.mean(hist), statistics.pstdev(hist)) if hist else None


def _random_metrics(rng):
    m = {"attempted": rng.choice([0, 5, 10, 500]), "released_share": rng.choice([0.0, 0.2, 0.6])}
    for metric in METRICS:
        roll = rng.random()
        if roll < 0.1:
            continue  # metric absent
        m[metric] = rng.choice([0, 1, 0.0, 0.1, 1 / 3, 0.98]) if roll < 0.4 else round(rng.random(), rng.randint(1, 17))
    return m


def test_incremental_baseline_matches_full_rescan(tmp_path):
    rng = random.Random(7)
    store = RunStore(str(tmp_path / "run.db"))
    run = store.create_run("src", "nimbus", {"types": ["Observation", "Patient"]})
    batches = []
    for i in range(300):
        rtype = rng.choice(["Observation", "Observation", "Patient"])
        bid = store.create_batch(run, rtype, "")
        for metric in METRICS:  # evaluated while the new batch is still open, as the runner does
            assert rules._baseline_stats(store, run, rtype, metric, bid) == _expected(store, run, rtype, metric, bid)
        status = rng.choice(["loaded", "loaded", "loaded", "no_writes"])
        store.finish_batch(bid, status, {}, _random_metrics(rng) if rng.random() > 0.05 else {})
        batches.append((bid, rtype))
        if i % 37 == 36:  # a revert changes which earlier batches count
            store.set_batch_status(rng.choice(batches)[0], "reverted")
        if i % 53 == 52:  # another process reverts a counted batch; data_version must invalidate the cache
            counted = [b["id"] for b in store.batches(run, "Observation") if b["status"] == "loaded"
                       and (b["metrics"] or {}).get("attempted", 0) >= 10
                       and (b["metrics"] or {}).get("released_share", 0) <= 0.5]
            other = sqlite3.connect(str(tmp_path / "run.db"))
            other.execute("UPDATE batches SET status='reverted' WHERE id=?", (rng.choice(counted),))
            other.commit()
            other.close()
        for rtype in ("Observation", "Patient"):
            exclude = rng.choice(batches)[0]  # excluding an already-counted batch must subtract it exactly
            for metric in METRICS:
                assert rules._baseline_stats(store, run, rtype, metric, exclude) == _expected(store, run, rtype, metric, exclude)


def test_non_finite_values_behave_like_statistics(tmp_path):
    store = RunStore(str(tmp_path / "run.db"))
    run = store.create_run("src", "nimbus", {"types": ["Observation"]})
    for v in (0.5, float("inf"), 0.25, 0.75):
        bid = store.create_batch(run, "Observation", "")
        store.finish_batch(bid, "loaded", {}, {"attempted": 100, "fidelity_mean": v})
    hist = rules._baseline(store, run, "Observation", "fidelity_mean", "none")
    # The exception type differs across Python versions (3.12: AttributeError, 3.13: ValueError); match it.
    with pytest.raises(Exception) as expected:
        statistics.pstdev(hist)
    with pytest.raises(expected.type):
        rules._baseline_stats(store, run, "Observation", "fidelity_mean", "none")
