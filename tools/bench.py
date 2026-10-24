"""Profile a deterministic, synthetic Halcyon → Bridge → Nimbus conversion.

Examples:
  python tools/bench.py --patients 5000 --seed 42 --profile-out /tmp/bridge.prof
  python -m pstats /tmp/bridge.prof

Times are comparable only with the same hardware, seed, patient count and revision.
The --profile-out option runs cProfile around the actual conversion.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import tempfile
import time
import sys
import threading
import sqlite3
import resource
from pathlib import Path

from bridge.load.client import connect
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore
from testbed.halcyon.generator import generate
from testbed.simulated_user import SimulatedAnalyst
from bridge.reconcile.answers import answer


def progress(stage: str, started: float, **details: object) -> None:
    elapsed = round(time.perf_counter() - started, 1)
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    print(json.dumps({"stage": stage, "elapsed_seconds": elapsed, "peak_rss_mb": rss_mb, **details}),
          file=sys.stderr, flush=True)


def monitor_database(path: Path, stop: threading.Event, started: float) -> None:
    """Observe committed progress via a separate connection without blocking converter writes."""
    while not stop.wait(15):
        try:
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
            try:
                run = db.execute("SELECT id,status,pass_count FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
                if run:
                    batches = db.execute("SELECT COUNT(*), COALESCE(SUM(json_extract(counts,'$.attempted')),0) FROM batches WHERE run_id=?", (run[0],)).fetchone()
                    progress("heartbeat", started, run_status=run[1], passes=run[2],
                             completed_batches=batches[0], attempted_records=batches[1])
                else:
                    progress("heartbeat", started, state="generating_or_preparing")
            finally:
                db.close()
        except (sqlite3.Error, OSError) as exc:
            progress("heartbeat", started, note=type(exc).__name__)


def benchmark(patients: int = 5000, seed: int = 42, profile_out: str | None = None, *, without_index: bool = False, first_pass_only: bool = False) -> dict:
    if patients < 1:
        raise ValueError("patients must be positive")
    with tempfile.TemporaryDirectory(prefix="bridge-bench-") as scratch:
        root = Path(scratch)
        export = root / "export"
        began = time.perf_counter()
        progress("generation_started", began, patients=patients)
        generate(export, seed=seed, patients=patients)
        progress("generation_completed", began, patients=patients)
        generation_seconds = time.perf_counter() - began
        db = root / "run.db"
        target = f"embedded:{root / 'nimbus.db'}"
        store = RunStore(str(db))
        if without_index:
            store.db.execute("DROP INDEX IF EXISTS ix_records_blocker_key")
        runner = Runner(store, connect(target))
        profiler = cProfile.Profile() if profile_out else None
        began = time.perf_counter()
        stopped = threading.Event()
        watcher = threading.Thread(target=monitor_database, args=(db, stopped, began), daemon=True)
        watcher.start()
        progress("conversion_started", began, patients=patients)
        if profiler:
            profiler.enable()
        try:
            run_id = runner.start(str(export), target)
            analyst = SimulatedAnalyst(export)
            if first_pass_only:
                # Profile the 5k-patient initial pass without measuring a paused run as a full conversion.
                pass
            else:
                for _ in range(100):
                    state = store.run(run_id)["status"]
                    blocking = [q for q in store.questions(run_id) if q["blocking"]]
                    if state not in ("paused", "completed_with_exceptions") and not blocking:
                        break
                    if not blocking and state != "paused":
                        break
                    for question in blocking:
                        detail = store.question(question["id"])
                        linked = detail["affected"]
                        rec = store.record(run_id, linked[0]["rtype"], linked[0]["source_key"]) if linked else None
                        source = rec["source"] if rec else None
                        option, value, why = analyst.choose(detail, source)
                        answer(store, question["id"], option, value, analyst.name, why)
                    runner.resume(run_id, "synthetic analyst benchmark", analyst.name)
                else:
                    raise RuntimeError("benchmark did not resolve pauses within 100 rounds")
        finally:
            stopped.set()
            watcher.join(timeout=2)
            if profiler:
                profiler.disable()
        conversion_seconds = time.perf_counter() - began
        progress("conversion_completed", began, patients=patients, duration=round(conversion_seconds, 2))
        if profiler:
            profiler.dump_stats(profile_out)
            pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(30)
        counts = store.status_counts(run_id)
        status = store.run(run_id)["status"]
        if not first_pass_only and status not in ("completed", "completed_with_exceptions"):
            raise RuntimeError(f"benchmark did not finish: {status}")
        return {
            "seed": seed, "patients": patients, "without_index": without_index, "first_pass_only": first_pass_only,
            "generation_seconds": round(generation_seconds, 3),
            "conversion_seconds": round(conversion_seconds, 3),
            "records_by_status": counts,
            "run_status": status,
            "profile_file": profile_out,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patients", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile-out", default=None)
    parser.add_argument("--without-index", action="store_true", help="drop blocker index for same-revision control")
    parser.add_argument("--first-pass-only", action="store_true", help="profile initial 5k processing only; not a completed conversion")
    args = parser.parse_args()
    print(json.dumps(benchmark(args.patients, args.seed, args.profile_out, without_index=args.without_index, first_pass_only=args.first_pass_only), indent=2))


if __name__ == "__main__":
    main()
