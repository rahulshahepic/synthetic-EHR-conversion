"""List reconciliation questions that a terminology crosswalk row could have prevented.

Runs a Bridge conversion over a Halcyon export (in-process, embedded Nimbus,
driving the run to completion the same way tests/bridge/conftest.py does) and
then inspects every question the run filed. A question counts as
crosswalk-preventable when its kind is one whose mapper consults a terminology
CSV in src/bridge/terminology/data/ and its match_key is absent from that CSV:
adding a row for the key would have prevented the question entirely.

Kinds and the crosswalk each consults:

    unmapped_medication -> formulary_rxnorm.csv  (Terminology.formulary)
    unmapped_lab        -> lab_loinc.csv         (Terminology.labs)
    unmapped_vaccine    -> vaccine_cvx.csv       (Terminology.vaccines)
    unmapped_icd9       -> icd9_icd10.csv        (Terminology.icd9)
    unmapped_local_dx   -> local_dx.csv          (Terminology.local_dx)
    unknown_visit_type  -> visit_class.csv       (Terminology.visit_class)

Other question kinds are deliberately NOT listed, because no added row could
have prevented them: 1:many choices (icd9_one_to_many, retired_icd10) are
*caused* by crosswalk rows and need a human pick among candidates; identity
matches, missing demographics, shared departments, generic accounts and the
like are not terminology lookups; unmapped_charge is governed by the source
charge master (CPT/HCPCS), not by these CSVs; free-text problems flow through
the free_text_problem question/rule mechanism by design (there is no CSV for
them). The extension workflow this tool supports lives in task T-105: run it,
add rows for what should map, and document what stays as a deliberate gap in
src/bridge/terminology/data/README.md.

Usage:
    python tools/crosswalk_gaps.py --source exports/seed42 [--run-db runs/gaps.db]

Output is one line per preventable (kind, key), sorted by (kind, key), plus a
summary comment line; it is deterministic for a given export and crosswalk
state. Requires the project installed (pip install -e .) or src/ on the path.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

try:
    import bridge  # noqa: F401
except ImportError:  # running from a bare checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bridge.load.client import connect
from bridge.reconcile.answers import answer
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore
from bridge.terminology import TERMS, Terminology

# question kind -> Terminology attribute holding the crosswalk the mapper consulted
CROSSWALK_FOR_KIND: dict[str, str] = {
    "unmapped_medication": "formulary",
    "unmapped_lab": "labs",
    "unmapped_vaccine": "vaccines",
    "unmapped_icd9": "icd9",
    "unmapped_local_dx": "local_dx",
    "unknown_visit_type": "visit_class",
}


def find_gaps(questions: Iterable[dict[str, Any]], terms: Terminology = TERMS) -> list[tuple[str, str, int]]:
    """Return sorted (kind, key, affected_count) for every crosswalk-preventable question.

    Pure: takes question dicts as produced by RunStore.questions() and a
    Terminology. A question whose key has since gained a crosswalk row is not
    a gap anymore and is skipped (the row now prevents it); keys aggregated if
    a (kind, key) pair somehow appears twice.
    """
    found: dict[tuple[str, str], int] = {}
    for q in questions:
        attr = CROSSWALK_FOR_KIND.get(q["kind"])
        if attr is None:
            continue
        key = q["match_key"]
        if key == "(blank)":  # no source code at all; there is no key a row could carry
            continue
        if key in getattr(terms, attr):
            continue
        found[(q["kind"], key)] = found.get((q["kind"], key), 0) + int(q.get("affected_count") or 0)
    return sorted((kind, key, n) for (kind, key), n in found.items())


def _drive(store: RunStore, runner: Runner, run_id: str, max_pauses: int = 50) -> str:
    """Answer every blocking question with its first option and resume until
    the run stops pausing (mirrors tests/bridge/conftest.py's drive fixture),
    so questions from every record type get filed, not just the first batch's."""
    for _ in range(max_pauses):
        status = store.run(run_id)["status"]
        open_blocking = [q for q in store.questions(run_id, "open") if q["blocking"]]
        if status != "paused" and not (status == "completed_with_exceptions" and open_blocking):
            return status
        for q in store.questions(run_id, "open"):
            if q["blocking"]:
                opt = q["options"][0]["key"]
                needs = next(o for o in q["options"] if o["key"] == opt).get("needs_value")
                answer(store, q["id"], opt, value="2000-01-01" if needs else None,
                       answered_by="tool:crosswalk_gaps")
        runner.resume(run_id, "crosswalk_gaps", "tool:crosswalk_gaps")
    raise RuntimeError("run kept pausing")


def run_gaps(source: str, run_db: str) -> list[tuple[str, str, int]]:
    """Convert the Halcyon export at `source` and return its crosswalk gaps."""
    store = RunStore(run_db)
    runner = Runner(store, connect("embedded::memory:"))
    run_id = runner.start(source)
    _drive(store, runner, run_id)
    return find_gaps(store.questions(run_id, status=None))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", required=True, help="Halcyon export directory to convert")
    p.add_argument("--run-db", default=None,
                   help="run DB path (default: a fresh temporary file; the run is kept for inspection)")
    args = p.parse_args(argv)
    run_db = args.run_db or str(Path(tempfile.mkdtemp(prefix="crosswalk_gaps_")) / "run.db")
    gaps = run_gaps(args.source, run_db)
    for kind, key, n in gaps:
        print(f"{kind}\t{key}\taffected={n}")
    print(f"# {len(gaps)} crosswalk-preventable question(s); run DB: {run_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
