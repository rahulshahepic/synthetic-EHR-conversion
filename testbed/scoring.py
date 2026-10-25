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

# Source fields whose value must reach Nimbus unchanged (as local wall-clock time or calendar date):
# (rtype, Observation kind or None, source field, dotted path in the mapped payload).
FAITHFUL_TIMES = [
    ("Encounter", None, "ADMIT_DT", "period.start"),
    ("Encounter", None, "DISCH_DT", "period.end"),
    ("Observation", "lab", "COLLECT_DT", "effective"),
    ("Observation", "vital", "TAKEN_DT", "effective"),
    ("Appointment", None, "APPT_DT", "start"),
    ("DocumentReference", None, "NOTE_DT", "date"),
]
FAITHFUL_DATES = [
    ("Condition", None, "ONSET_DT", "onsetDate"),
    ("Condition", None, "RESOLVED_DT", "abatementDate"),
    ("MedicationRequest", None, "START_DT", "authoredOn"),
    ("Immunization", None, "ADMIN_DT", "occurrenceDate"),
    ("ChargeItem", None, "POST_DT", "serviceDate"),
    ("AllergyIntolerance", None, "ENTERED_DT", "recordedDate"),
    ("Coverage", None, "EFF_DT", "period.start"),
]


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


def _path(payload: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(payload, dict):
            return None
        payload = payload.get(part)
    return payload


def _expected_local(raw: str, kind: str) -> str | None:
    """Independent reading of a Halcyon value: YYYYMMDD[HHMM[SS]] -> ISO local prefix, else None."""
    raw = raw.strip()
    if not raw.isdigit():
        return None
    if kind == "date" and len(raw) == 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if kind == "time" and len(raw) in (12, 14):
        iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T{raw[8:10]}:{raw[10:12]}"
        return iso + (f":{raw[12:14]}" if len(raw) == 14 else "")
    return None


class _Check:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.examples: list[dict[str, Any]] = []

    def record(self, key: str, expected: Any, got: Any, *, skipped: bool = False) -> None:
        if skipped:
            self.counts["skipped"] += 1
        elif got is None:
            self.counts["missing"] += 1
        else:
            self.counts["checked"] += 1
            if got != expected:
                self.counts["mismatched"] += 1
                if len(self.examples) < 5:
                    self.examples.append({"key": key, "expected": expected, "got": got})

    def report(self) -> dict[str, Any]:
        return {"checked": self.counts["checked"], "mismatched": self.counts["mismatched"],
                "missing": self.counts["missing"], "skipped": self.counts["skipped"],
                "mismatch_examples": self.examples}


def _value_checks(db: sqlite3.Connection, run_id: str, truth: dict[str, Any],
                  persons: dict[str, list[str]]) -> dict[str, Any]:
    """Check loaded values against the raw source and the answer key.

    Surfacing (above) asks whether Bridge *noticed* a problem; this asks whether what it loaded is
    *right*: timestamps and dates must keep their source wall-clock value, and fields the generator
    knows the truth for must match it. Only loaded records are checked; DST-adjusted times are skipped.
    """
    checks: dict[str, _Check] = defaultdict(_Check)
    person_of = {pat: person for person, pats in persons.items() for pat in pats}
    rows = db.execute("SELECT rtype, source_key, source, mapped, annotations FROM records "
                      "WHERE run_id=? AND status='loaded'", (run_id,))
    for row in rows:
        rtype, key = row["rtype"], row["source_key"]
        src = json.loads(row["source"]) if row["source"] else {}
        mapped = json.loads(row["mapped"]) if row["mapped"] else {}
        notes = " ".join(str(a.get("note") or "") for a in json.loads(row["annotations"] or "[]") if isinstance(a, dict))
        dst_adjusted = "DST" in notes
        for specs, kind in ((FAITHFUL_TIMES, "time"), (FAITHFUL_DATES, "date")):
            for spec_rtype, obs_kind, field, path in specs:
                if rtype != spec_rtype or (obs_kind and src.get("kind") != obs_kind) or not src.get(field, "").strip():
                    continue
                expected = _expected_local(src[field], kind)
                got = _path(mapped, path)
                if isinstance(got, str):
                    got = got[:len(expected)] if expected else got
                checks[f"{rtype}.{path} = {field}"].record(
                    key, expected, got, skipped=expected is None or (kind == "time" and dst_adjusted))
        if rtype == "Condition" and src.get("DX_ID") in truth.get("dx", {}):
            codes = [c.get("code") for c in _path(mapped, "code.coding") or [] if c.get("system") == "ICD-10-CM"]
            checks["Condition ICD-10 code = answer key"].record(key, truth["dx"][src["DX_ID"]], codes[0] if codes else None)
        elif rtype == "Appointment" and src.get("APPT_ID") in truth.get("appt_status", {}):
            want = truth["appt_status"][src["APPT_ID"]]  # None: no Nimbus status exists (scored as surfacing)
            checks["Appointment status = answer key"].record(key, want, mapped.get("status"), skipped=want is None)
        elif rtype == "AllergyIntolerance" and src.get("ALG_ID") in truth.get("allergy", {}):
            coding = (_path(mapped, "substance.coding") or [None])[0]
            want = truth["allergy"][src["ALG_ID"]]  # None: the allergen has no standard code and must stay uncoded
            checks["Allergy substance code = answer key"].record(
                key, list(want) if want else "uncoded", [coding.get("system"), coding.get("code")] if coding else "uncoded")
        elif rtype == "Practitioner" and key in truth.get("provider_specialty", {}):
            checks["Practitioner specialty = answer key"].record(key, truth["provider_specialty"][key], mapped.get("specialty"))
        elif rtype == "Patient":
            members = [m.get("PAT_ID") for m in src.get("members", [])]
            people = {person_of.get(m) for m in members} - {None}
            if len(people) == 1:
                person = truth.get("person", {}).get(people.pop())
                if person:
                    checks["Patient birthDate = answer key"].record(key, person["dob"], mapped.get("birthDate"))
            phones = {t.get("value") for t in mapped.get("telecom", [])}
            # Policy: the newest demographics win across merged charts (chart rows as of their LAST_UPD day).
            stamps = [m.get("LAST_UPD", "") + "0000" for m in src.get("members", [])]
            stamps += [(a or {}).get("at", "") for a in src.get("a08", {}).values()]
            for m in members:
                if m in truth.get("a08_demographics", {}):
                    want = truth["a08_demographics"][m]["phone"]
                    at = (src.get("a08", {}).get(m) or {}).get("at", "")
                    superseded = any(other > at for other in stamps)
                    # A 7-digit A08 phone has no area code: the full number is unrecoverable from the source.
                    raw = (src.get("a08", {}).get(m) or {}).get("phone") or ""
                    digits = re.sub(r"\D", "", re.split(r"(?i)x|ext", raw)[0])
                    checks["Patient phone = latest ADT A08"].record(
                        key, want, want if want in phones else sorted(phones) or None,
                        skipped=len(digits) < 10 or not at or superseded)
    out = {name: check.report() for name, check in sorted(checks.items())}
    checked = sum(c["checked"] for c in out.values())
    mismatched = sum(c["mismatched"] for c in out.values())
    return {"checks": out, "checked": checked, "mismatched": mismatched,
            "accuracy": (checked - mismatched) / checked if checked else 1.0}


def score(export_dir: Path | str, run_db: Path | str, run_id: str | None = None) -> dict[str, Any]:
    """Return a JSON-serializable scoring report for one Bridge run."""
    export_dir = Path(export_dir)
    issues_path = export_dir / "answer_key" / "issues.jsonl"
    persons_path = export_dir / "answer_key" / "persons.json"
    issues = [json.loads(line) for line in issues_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    persons = json.loads(persons_path.read_text(encoding="utf-8"))
    truth_path = export_dir / "answer_key" / "truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8")) if truth_path.exists() else {}

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
        values = _value_checks(db, rid, truth, persons)

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
        "values": values,
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
    values = report.get("values")
    if values:
        lines.extend([
            "## Loaded values",
            f"Overall: {values['checked'] - values['mismatched']}/{values['checked']} correct ({values['accuracy']:.1%})",
            "",
            "| Check | Checked | Mismatched | Missing | Skipped | Example mismatch |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ])
        for name, c in values["checks"].items():
            ex = c["mismatch_examples"][0] if c["mismatch_examples"] else None
            example = f"{ex['key']}: expected {ex['expected']}, got {ex['got']}" if ex else ""
            lines.append(f"| {cell(name)} | {c['checked']} | {c['mismatched']} | {c['missing']} | {c['skipped']} | {cell(example)} |")
        lines.append("")
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
