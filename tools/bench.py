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
from pathlib import Path

from bridge.load.client import connect
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore
from testbed.halcyon.generator import generate


def benchmark(patients: int = 5000, seed: int = 42, profile_out: str | None = None) -> dict:
    if patients < 1:
        raise ValueError("patients must be positive")
    with tempfile.TemporaryDirectory(prefix="bridge-bench-") as scratch:
        root = Path(scratch)
        export = root / "export"
        began = time.perf_counter()
        generate(export, seed=seed, patients=patients)
        generation_seconds = time.perf_counter() - began
        db = root / "run.db"
        target = f"embedded:{root / 'nimbus.db'}"
        store = RunStore(str(db))
        runner = Runner(store, connect(target))
        profiler = cProfile.Profile() if profile_out else None
        began = time.perf_counter()
        if profiler:
            profiler.enable()
        try:
            run_id = runner.start(str(export), target)
        finally:
            if profiler:
                profiler.disable()
        conversion_seconds = time.perf_counter() - began
        if profiler:
            profiler.dump_stats(profile_out)
            pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(30)
        counts = store.status_counts(run_id)
        return {
            "seed": seed, "patients": patients,
            "generation_seconds": round(generation_seconds, 3),
            "conversion_seconds": round(conversion_seconds, 3),
            "records_by_status": counts,
            "run_status": store.run(run_id)["status"],
            "profile_file": profile_out,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patients", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile-out", default=None)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.patients, args.seed, args.profile_out), indent=2))


if __name__ == "__main__":
    main()
