"""Score a synthetic Halcyon-to-Bridge conversion against the generator's answer key.

This is a TESTBED-ONLY tool: it reads answer_key/ and the Bridge run SQLite
database directly, and deliberately never imports bridge or nimbus.

Usage:
    python -m testbed.scoring --export exports/seed42 --run-db runs/r1.db
    python -m testbed.scoring --export exports/seed42 --run-db runs/r1.db \
        --json-out score.json --md-out score.md

"Surfaced" means a question was linked to a matching staged record, the record
has a lossy annotation (inferred/degraded/defaulted/dropped), or its current
status is held/dropped/superseded. This measures surfacing, NOT correctness of
the chosen remediation. Unmatched source issues are reported separately and
are never credited as surfaced. Identity accuracy compares pairwise grouping
of every source PAT_ID, counting absent xrefs as separate singletons.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import chain
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import quote


LOSSY = frozenset({"inferred", "degraded", "defaulted", "dropped"})
SURFACED_STATUSES = frozenset({"held", "dropped", "superseded"})
_REGISTRY_KEY = re.compile(r"^REG-[^-]+-(.+?)-([^-]+)-(\d{4}-\d{2}-\d{2})$")


def _pairs(n: int) -> int:
    return n * (n - 1) // 2


def _identity(persons: dict[str, list[str]], xrefs: dict[str, Any]) -> dict[str, Any]:
    """Compute pairwise precision/recall in O(PAT_IDs), not O(PAT_IDs squared)."""
    truth_counts: Counter[str] = Counter()
    predicted_counts: Counter[tuple[str, str]] = Counter()
    intersection_counts: Counter[tuple[str, tuple[str, str]]] = Counter()
    seen: set[str] = set()
    mapped = 0
    for person, ids in persons.items():
        for pat_id in ids:
            if pat_id in seen:
                raise ValueError(f"PAT_ID {pat_id!r} belongs to multiple answer-key persons")
            seen.add(pat_id)
            # An absent xref must NOT make all unknown patients look merged.
            group = ("xref", json.dumps(xrefs[pat_id], sort_keys=True)) if (
                pat_id in xrefs and xrefs[pat_id] is not None
            ) else ("missing", pat_id)
            mapped += int(group[0] == "xref")
            truth_counts[person] += 1
            predicted_counts[group] += 1
            intersection_counts[(person, group)] += 1

    actual_pairs = sum(_pairs(n) for n in truth_counts.values())
    predicted_pairs = sum(_pairs(n) for n in predicted_counts.values())
    correct_pairs = sum(_pairs(n) for n in intersection_counts.values())
    return {
        "patients": len(seen),
        "mapped_patients": mapped,
        "missing_xrefs": len(seen) - mapped,
        "true_positive_pairs": correct_pairs,
        "predicted_positive_pairs": predicted_pairs,
        "actual_positive_pairs": actual_pairs,
        # Vacuous scores are 1.0 if no positive pairs exist in that denominator.
        "pairwise_precision": correct_pairs / predicted_pairs if predicted_pairs else 1.0,
        "pairwise_recall": correct_pairs / actual_pairs if actual_pairs else 1.0,
    }


def _record_index(db: sqlite3.Connection, run_id: str) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]], set[tuple[str, str]]
]:
    """Index records by answer-key table/key, including expanded feed records."""
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rows = db.execute(
        "SELECT rtype, source_key, status, lineage, annotations FROM records WHERE run_id=?",
        (run_id,),
    )
    for row in rows:
        lineage = json.loads(row["lineage"]) if row["lineage"] else {}
        annotations = json.loads(row["annotations"]) if row["annotations"] else []
        rec = {
            "rtype": row["rtype"], "source_key": row["source_key"],
            "status": row["status"],
            "lossy": any(isinstance(a, dict) and a.get("klass") in LOSSY for a in annotations),
            "column": lineage.get("column"),
        }
        table = lineage.get("table")
        ids = lineage.get("id", [])
        if not isinstance(ids, list):
            ids = [ids]
        for key in ids:
            if table and key is not None:
                index[(str(table), str(key))].append(rec)

        # LAB_RESULT rows are staged as LAB-<accession>:<test>, including
        # recent feed-only labs whose answer-key key is accession:test.
        if rec["rtype"] == "Observation" and rec["source_key"].startswith("LAB-"):
            index[("LAB_RESULT", rec["source_key"][4:])].append(rec)

        # Registry-only rows have no source DB primary key. The answer key
        # stores MRN:CVX:YYYY-MM-DD, while Bridge adds FAC and REG- prefix.
        if rec["rtype"] == "Immunization":
            match = _REGISTRY_KEY.fullmatch(rec["source_key"])
            if match:
                mrn, cvx, date = match.groups()
                index[("registry", f"{mrn}:{cvx}:{date}")].append(rec)

    questions = {
        (r["rtype"], r["source_key"])
        for r in db.execute(
            "SELECT qr.rtype, qr.source_key FROM question_records qr "
            "JOIN questions q ON q.id=qr.question_id WHERE q.run_id=?",
            (run_id,),
        )
    }
    return index, questions


def score(export_dir: Path | str, run_db: Path | str, run_id: str | None = None) -> dict[str, Any]:
    """Return a JSON-serializable scoring report for one Bridge run."""
    export_dir = Path(export_dir)
    issues_path = export_dir / "answer_key" / "issues.jsonl"
    persons_path = export_dir / "answer_key" / "persons.json"
    issues = [json.loads(line) for line in issues_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    persons = json.loads(persons_path.read_text(encoding="utf-8"))

    # Open read-only so an invalid path never creates an empty run database.
    db_path = Path(run_db).resolve()
    uri = "file:" + quote(str(db_path), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        if run_id is None:
            row = db.execute("SELECT id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
        else:
            row = db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Bridge run {run_id or '(latest)'} not found")
        rid = row["id"]
        index, questions = _record_index(db, rid)
        xrefs = {
            row["key"]: json.loads(row["value"]) if row["value"] is not None else None
            for row in db.execute("SELECT key, value FROM xref WHERE run_id=? AND kind='pat'", (rid,))
        }

    totals: dict[str, Counter[str]] = defaultdict(Counter)
    missed: dict[str, list[str]] = defaultdict(list)
    unmatched: dict[str, list[str]] = defaultdict(list)
    for issue in issues:
        kind = str(issue["type"])
        table, key = str(issue["table"]), str(issue["key"])
        counts = totals[kind]
        counts["total"] += 1
        matches = index.get((table, key), [])
        # VITALS rows expand to one Observation per field; a BP problem
        # must not get credit for a lossy annotation on unrelated weight.
        if table == "VITALS" and issue.get("field"):
            matches = [r for r in matches if r["column"] == issue["field"]]
        # A single record may be indexed via multiple aliases; dedupe it.
        matches = list({(r["rtype"], r["source_key"]): r for r in matches}.values())
        if not matches:
            counts["unmatched"] += 1
            if len(unmatched[kind]) < 5:
                unmatched[kind].append(f"{table}/{key}")
            continue
        surfaced = any(
            r["status"] in SURFACED_STATUSES or r["lossy"]
            or (r["rtype"], r["source_key"]) in questions
            for r in matches
        )
        if surfaced:
            counts["surfaced"] += 1
        else:
            counts["missed"] += 1
            if len(missed[kind]) < 5:
                missed[kind].append(f"{table}/{key}")

    by_type = {
        kind: {
            "total": totals[kind]["total"],
            "surfaced": totals[kind]["surfaced"],
            "missed": totals[kind]["missed"],
            "unmatched": totals[kind]["unmatched"],
            "surfacing_rate": totals[kind]["surfaced"] / totals[kind]["total"],
            "missed_examples": missed.get(kind, []),
            "unmatched_examples": unmatched.get(kind, []),
        }
        for kind in sorted(totals)
    }
    total = sum(x["total"] for x in by_type.values())
    surfaced = sum(x["surfaced"] for x in by_type.values())
    return {
        "run_id": rid,
        "issue_types": by_type,
        "overall": {
            "total": total, "surfaced": surfaced,
            "missed": sum(x["missed"] for x in by_type.values()),
            "unmatched": sum(x["unmatched"] for x in by_type.values()),
            "surfacing_rate": surfaced / total if total else 1.0,
        },
        "identity": _identity(persons, xrefs),
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Human-readable, compact scorecard; all source strings are escaped."""
    def cell(value: Any) -> str:
        return str(value).replace("|", r"\|").replace("\n", " ").replace("\r", " ")

    lines = [
        f"# Conversion score: {cell(report['run_id'])}",
        "",
        "| Issue type | Planted | Surfaced | Missed | Unmatched | Surfacing rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for kind, counts in report["issue_types"].items():
        lines.append(
            f"| {cell(kind)} | {counts['total']} | {counts['surfaced']} | "
            f"{counts['missed']} | {counts['unmatched']} | {counts['surfacing_rate']:.1%} |"
        )
    overall = report["overall"]
    lines.append(
        f"| **Total** | **{overall['total']}** | **{overall['surfaced']}** | "
        f"**{overall['missed']}** | **{overall['unmatched']}** | **{overall['surfacing_rate']:.1%}** |"
    )
    identity = report["identity"]
    lines.extend([
        "", "## Identity grouping",
        f"PAT IDs: {identity['patients']} ({identity['mapped_patients']} mapped; "
        f"{identity['missing_xrefs']} without xref)",
        f"Pairwise precision: {identity['pairwise_precision']:.1%} "
        f"({identity['true_positive_pairs']}/{identity['predicted_positive_pairs']} positive predicted pairs)",
        f"Pairwise recall: {identity['pairwise_recall']:.1%} "
        f"({identity['true_positive_pairs']}/{identity['actual_positive_pairs']} actual positive pairs)",
        "",
        "Surfacing counts include linked questions, lossy fidelity annotations, "
        "or held/dropped/superseded records. Unmatched issues are not surfaced.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a synthetic Bridge run against the Halcyon answer key")
    parser.add_argument("--export", type=Path, required=True, help="Halcyon export containing answer_key/")
    parser.add_argument("--run-db", type=Path, required=True, help="Bridge run SQLite DB")
    parser.add_argument("--run-id", help="run to score (default: latest)")
    parser.add_argument("--json-out", type=Path, help="optional JSON output file")
    parser.add_argument("--md-out", type=Path, help="optional Markdown output file")
    args = parser.parse_args(argv)
    report = score(args.export, args.run_db, args.run_id)
    as_json = json.dumps(report, indent=2)
    as_markdown = render_markdown(report)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(as_json + "\n", encoding="utf-8")
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(as_markdown, encoding="utf-8")
    print(as_json)
    print(as_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
