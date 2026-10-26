"""Grade a Meridian interview + conversion against the answer key (TESTBED ONLY; reads answer_key/).

  python -m testbed.meridian.grade --export exports/meridian --run-db runs/meridian.db \\
      --spec src/bridge/interview/specs/meridian/spec.json --md-out docs/meridian-results.md

Two parts:
1. Interview scorecard: every entry in the estate grading ledger gets a verdict computed from the
   generated spec (caught-by-profiling / -analyst / -documents / -interviewer, routed-to-runtime-
   question, swallowed, or missed).
2. Conversion checks: values Bridge loaded into Nimbus compared with ground truth (time zones,
   codes, units, identity...), plus the generic surfacing/identity score from testbed.scoring.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from testbed import scoring

# grading entry -> (subject, predicate, marker of the true position, marker of the false position)
CHECKS: dict[str, tuple[str, str, Any, Any]] = {
    "guide_version_skew": ("estate", "dictionary_status", "stale", "current"),
    "guide_timezone": ("profile", "facility_tz", {"SRC": "America/Phoenix"}, {"SRC": "America/Denver"}),
    "guide_dx_decimal": ("field:PROBLEM.DAT.DX_CODE", "convention", "stripped", "stored with the decimal point"),
    "guide_sex_codes": ("field:PERSON.DAT.SEX_CD", "convention", "3=X", "0=unknown"),
    "guide_rel_codes": ("field:INSCOV.DAT.REL_CD", "convention", "C=child", "D=dependent"),
    "guide_visit_types": ("field:VISIT.DAT.VISIT_TYPE", "convention", "TH telehealth", None),
    "guide_lab_timestamp": ("field:LABRES.DAT.COLLECTED_TS", "convention", "DD-MON-YY", "YYYY-MM-DD"),
    "guide_result_status": ("field:LABRES.DAT.RESULT_STATUS", "convention", "X=cancelled", "P=preliminary"),
    "guide_vs_unit": ("field:VITALS.DAT.VS_UNIT", "convention", "blank at HVMC", "always populated"),
    "guide_appt_status": ("field:APPT.DAT.APPT_STATUS", "convention", "BMP", None),
    "guide_stale_immune": ("file:IMMUNE", "presence", "absent", "listed"),
    "undocumented_placeholder_dob": ("field:PERSON.DAT.BIRTH_DT", "convention", "placeholder", None),
    "belief_mpi_no_duplicates": ("identity", "keying_story", {"true_duplicates": True}, {"true_duplicates": False}),
    "belief_cancelled_results_purged": ("field:LABRES.DAT.RESULT_STATUS", "convention", "X=cancelled", "purged"),
    "belief_blank_rxnorm_inactive": ("codeset:formulary", "handling_unmapped", "route every order", "skip"),
    "disagreement_duplicates": ("identity", "keying_story", {"true_duplicates": True}, {"true_duplicates": False}),
    "disagreement_sun_ridge_time": ("profile", "facility_tz", {"SRC": "America/Phoenix"}, {"SRC": "America/Denver"}),
}


def _has(value: Any, marker: Any) -> bool:
    if marker is None:
        return False
    if isinstance(marker, dict):
        return isinstance(value, dict) and all(value.get(k) == v for k, v in marker.items())
    return isinstance(value, str) and marker.lower() in value.lower()


def interview_scorecard(spec: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules = {(r["subject"], r["predicate"]): r for r in spec["rules"]}
    unknowns = {(u["subject"], u["predicate"]) for u in spec["known_unknowns"]}
    out = []
    for e in entries:
        subject, predicate, truth, false = CHECKS[e["id"]]
        rule = rules.get((subject, predicate))
        if rule and _has(rule["value"], truth):
            kind = rule["provenance"]["kind"]
            verdict = "caught-by-profiling" if rule["data_confirmed"] and kind == "profiler-data" else f"caught-by-{kind}"
            how = f"spec {rule['id']} ({kind}, data_confirmed={rule['data_confirmed']})"
        elif (subject, predicate) in unknowns:
            verdict, how = "routed-to-runtime-question", "known unknown in the spec"
        elif rule and _has(rule["value"], false):
            verdict, how = "swallowed", f"spec {rule['id']} adopted the false position"
        else:
            verdict, how = "missed", "no rule and no known unknown"
        out.append({"id": e["id"], "kind": e["kind"], "verdict": verdict, "how": how})
    return out


def _offset_ok(local_iso: str, tz: str) -> bool:
    dt = datetime.fromisoformat(local_iso)
    expected = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=ZoneInfo(tz)).utcoffset()
    return dt.utcoffset() == expected


def conversion_checks(export: Path, run_db: Path) -> dict[str, Any]:
    key = export / "answer_key"
    truth = json.loads((key / "truth.json").read_text())
    db = sqlite3.connect(f"file:{run_db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rid = db.execute("SELECT id FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()["id"]
    checks: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)

    def rec(name: str, ok: bool, example: str) -> None:
        checks[name]["checked"] += 1
        checks[name]["ok" if ok else "wrong"] += 1
        if not ok and len(examples[name]) < 3:
            examples[name].append(example)

    clinic_campus = {"HVFM": "HVMC", "HVIM": "HVMC", "HVED": "HVMC", "HV3W": "HVMC", "SRFM": "SRC", "SRUC": "SRC"}
    rows = db.execute("SELECT rtype, source_key, status, source, mapped FROM records WHERE run_id=?", (rid,))
    cancelled = set(truth["lab_cancelled"])
    for r in rows:
        src = json.loads(r["source"] or "{}")
        mapped = json.loads(r["mapped"] or "{}")
        loaded = r["status"] == "loaded"
        rt = r["rtype"]
        if rt == "Encounter" and loaded:
            campus = clinic_campus[src["DEPT_ID"]]
            start = mapped["period"]["start"]
            rec(f"Encounter time zone ({campus})", _offset_ok(start, truth["campus_tz"][campus]), f"{r['source_key']} {start}")
            rec("Encounter class = truth", mapped["class"] == truth["visit_class"][src["VISIT_ID"]], r["source_key"])
        elif rt == "Observation":
            if src.get("kind") == "lab":
                res_no = r["source_key"][4:]
                if res_no in cancelled:
                    rec("Cancelled lab results kept out of Nimbus", not loaded, r["source_key"])
                elif loaded:
                    rec("Lab collection time parsed (DD-MON-YY)", mapped.get("effective", "")[:4] >= "2005", mapped.get("effective", ""))
            elif loaded and src.get("FIELD") in ("WT", "TEMP", "HT"):
                fac = src["_PAT_FAC"]
                want = {"us": {"WT": "[lb_av]", "TEMP": "[degF]", "HT": "[in_i]"},
                        "metric": {"WT": "kg", "TEMP": "Cel", "HT": "cm"}}[truth["vital_units"][fac]][src["FIELD"]]
                rec(f"Vital unit = campus convention ({fac})", mapped["valueQuantity"]["unit"] == want, f"{r['source_key']} {mapped['valueQuantity']}")
        elif rt == "Coverage" and loaded:
            rec("Coverage relationship = truth", mapped["subscriberRelationship"] == truth["relationship"][r["source_key"]],
                f"{r['source_key']} {mapped['subscriberRelationship']} vs {truth['relationship'][r['source_key']]}")
        elif rt == "MedicationRequest":
            want = truth["rxnorm"].get(src["FORM_CODE"])
            if loaded:
                got = mapped["medication"]["coding"][0]["code"]
                rec("Medication RxNorm = truth", got == want, f"{r['source_key']} {got} vs {want}")
            elif want is None:
                rec("Uncodable meds kept out for pharmacist med rec", True, r["source_key"])
        elif rt == "Patient" and loaded:
            primary = src["primary"]
            want = truth["sex_code"][primary]
            got = mapped["sexAtBirth"]
            rec("Patient sex = truth (X marker -> unknown)", got == (want if want in ("male", "female") else "unknown"),
                f"{r['source_key']} {got} vs {want}")
    return {name: {**dict(c), "examples": examples.get(name, [])} for name, c in sorted(checks.items())}


def render_md(card: list[dict[str, Any]], conv: dict[str, Any], score: dict[str, Any]) -> str:
    lines = ["## Interview scorecard (estate grading ledger)", "", "| Entry | Kind | Verdict | How |", "|---|---|---|---|"]
    lines += [f"| {c['id']} | {c['kind']} | {c['verdict']} | {c['how']} |" for c in card]
    counts = Counter(c["verdict"] for c in card)
    lines += ["", "Summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), "",
              "## Conversion vs ground truth", "", "| Check | Checked | Correct | Wrong | Example of wrong |", "|---|---|---|---|---|"]
    for name, c in conv.items():
        lines.append(f"| {name} | {c.get('checked', 0)} | {c.get('ok', 0)} | {c.get('wrong', 0)} | {'; '.join(c['examples'])} |")
    ident = score["identity"]
    lines += ["", "## Identity and surfacing (testbed.scoring)", "",
              f"- Identity pairwise precision {ident['pairwise_precision']:.3f}, recall {ident['pairwise_recall']:.3f} "
              f"({ident['true_positive_pairs']}/{ident['actual_positive_pairs']} true duplicate pairs merged, "
              f"{ident['predicted_positive_pairs']} merges made)",
              f"- Planted issues surfaced: {score['overall']['surfaced']}/{score['overall']['total']} "
              f"({score['overall']['surfacing_rate']:.1%})", "",
              "| Issue type | Total | Surfaced | Missed | Unmatched |", "|---|---|---|---|---|"]
    for kind, b in sorted(score["issue_types"].items()):
        lines.append(f"| {kind} | {b['total']} | {b['surfaced']} | {b['missed']} | {b['unmatched']} |")
    vals = score.get("values", {})
    if vals:
        lines += ["", f"Value checks (testbed.scoring): {vals['checked'] - vals['mismatched']}/{vals['checked']} correct "
                      f"({vals['accuracy']:.1%})", "", "| Check | Checked | Mismatched |", "|---|---|---|"]
        for name, c in vals["checks"].items():
            lines.append(f"| {name} | {c['checked']} | {c['mismatched']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(prog="testbed.meridian.grade")
    ap.add_argument("--export", required=True)
    ap.add_argument("--run-db", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--md-out")
    ap.add_argument("--json-out")
    a = ap.parse_args()
    export = Path(a.export)
    entries = json.loads((export / "answer_key" / "estate_discrepancies.json").read_text())
    card = interview_scorecard(json.loads(Path(a.spec).read_text()), entries)
    conv = conversion_checks(export, Path(a.run_db).resolve())
    score = scoring.score(export, a.run_db)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps({"interview": card, "conversion": conv, "scoring": score}, indent=1, default=str))
    md = render_md(card, conv, score)
    if a.md_out:
        Path(a.md_out).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
