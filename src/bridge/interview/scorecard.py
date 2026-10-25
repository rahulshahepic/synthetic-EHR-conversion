"""The discrepancy scorecard: grading an interview against an estate's
grading ledger.

The mapping below (which claim subjects each grading entry is checked
against, and what strings mark the true and false positions) is explicit
data. The VERDICTS are computed from the generated spec: a verdict is
``caught-by-profiling`` or ``caught-by-analyst`` when the spec's rule for
the subject carries the true position with that provenance;
``swallowed`` when the spec adopted the false position;
``routed-to-runtime-question`` when the subject sits in the spec's known
unknowns (or is the identity-merge policy, which always routes).

Bridge code never reads the grading ledger itself: callers (tests, report
tooling) load it and hand the entries in as data.
"""
from __future__ import annotations

from typing import Any

CHECKS: dict[str, dict[str, Any]] = {
    "dict_version_skew": {"subjects": [("estate", "dictionary_status")],
                          "truth": "stale", "false": "current"},
    "dict_dob_format": {"subjects": [("field:REG.TXT.DOB", "convention")],
                        "truth": "YYMMDD", "false": "MMDDYY"},
    "dict_pivot_year": {"subjects": [("profile", "pivot_year")],
                        "truth_value": 30, "false_value": 50},
    "dict_potassium_unit": {"subjects": [("unit:POT", "unit")],
                            "truth": "MEQ/L", "false": "MG/DL"},
    "dict_stale_field_fax": {"subjects": [("field:REG.TXT.FAX", "convention")],
                             "truth": "absent", "false": "text(14)"},
    "dict_undocumented_yday": {"subjects": [("field:LAB.TXT.YDAY", "convention")],
                               "truth": "Julian", "false": None},
    "dict_undocumented_allergy_field": {"subjects": [("field:REG.TXT.ALGY", "convention")],
                                        "truth": "free-text", "false": None},
    "dict_appt_status_incomplete": {"subjects": [("field:APPT.TXT.STATUS", "convention")],
                                    "truth": "R", "false": None},
    "dict_registration_account_claim": {"subjects": [("identity", "keying_story")],
                                        "truth": "No master index",
                                        "false": "one account per patient"},
    "belief_lab_account_is_identity": {"subjects": [("identity", "keying_story")],
                                       "truth": "Departmental accounts",
                                       "false": "L number is the patient"},
    "belief_lab_nonnumeric_bench_error": {"subjects": [("field:LAB.TXT.RESULT", "convention")],
                                          "truth": "carried as text",
                                          "false": "excluded"},
    "belief_registration_merges_routine": {"special": "merge_policy"},
    "belief_pharmacy_misc_meds_skippable": {"subjects": [("codeset:misc_med", "handling")],
                                            "truth": "include", "false": "exclude"},
    "belief_systems_dictionary_current": {"subjects": [("estate", "dictionary_status")],
                                          "truth": "stale", "false": "current"},
    "disagreement_pivot_year": {"subjects": [("profile", "pivot_year")],
                                "truth_value": 30, "false_value": 50},
    "disagreement_duplicate_charts": {"special": "duplicate_charts"},
}


def _rule_for(spec: dict[str, Any], subject: str, predicate: str) -> dict[str, Any] | None:
    for r in spec.get("rules", []):
        if r.get("subject") == subject and r.get("predicate") == predicate:
            return r
    return None


def _unknown_for(spec: dict[str, Any], subject: str, predicate: str) -> bool:
    return any(u.get("subject") == subject and u.get("predicate") == predicate
               for u in spec.get("known_unknowns", []))


def _caught_by(rule: dict[str, Any]) -> str:
    kind = rule.get("provenance", {}).get("kind")
    if kind == "profiler-data":
        # Profiling credit requires data confirmation, not just the
        # kind label: an unconfirmed profiler-data rule proves nothing
        # was measured about this subject.
        return "caught-by-profiling" if rule.get("data_confirmed") else "swallowed"
    if kind == "analyst":
        return "caught-by-analyst"
    if kind == "dictionary":
        # Both call sites reach here only once the spec is known to
        # carry the true position, so a dictionary-kind winner means the
        # truth was established by comparing estate documents. That is a
        # catch, by documents — not a swallow, which means the false
        # position was adopted. If the rule is also data-confirmed, the
        # profiler's measurement did the work.
        return "caught-by-profiling" if rule.get("data_confirmed") \
            else "caught-by-documents"
    return "caught-by-profiling" if rule.get("data_confirmed") else "swallowed"


def _keying_position(value: dict[str, Any]) -> str | None:
    """The position a structured keying story takes (T-121: the keying
    story is a structured value — key fields, no action verb — so the
    text substring checks cannot grade it). The false family is a single
    key: one department's account number, or a master index, treated as
    identity itself. The true position is no master index, with charts
    keyed per department. Anything else takes neither position."""
    fields = value.get("key_fields") or []
    if value.get("master_index") is False and len(fields) >= 2:
        return "truth"
    if value.get("master_index") is True or len(fields) == 1:
        return "false"
    return None


def grade_entry(entry: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    check = CHECKS.get(entry["id"])
    if check is None:
        return {"id": entry["id"], "verdict": "ungraded",
                "detail": "no check mapping for this entry"}
    if check.get("special") == "merge_policy":
        policy = next((r for r in spec.get("rules", []) if r.get("id") == "SAFETY-IDENTITY-MERGE"),
                      None)
        routed = policy is not None and policy.get("value") == "route_to_reconciliation"
        return {"id": entry["id"],
                "verdict": "routed-to-runtime-question" if routed else "swallowed",
                "detail": "identity merges route to a human reconciliation question "
                          "by policy, whatever any analyst claimed" if routed else
                          "spec lacks the merge-routing policy rule"}
    if check.get("special") == "duplicate_charts":
        keying = _rule_for(spec, "identity", "keying_story")
        policy = next((r for r in spec.get("rules", []) if r.get("id") == "SAFETY-IDENTITY-MERGE"),
                      None)
        if keying is not None and policy is not None:
            return {"id": entry["id"], "verdict": "routed-to-runtime-question",
                    "detail": "the disagreement resolves into per-person matching "
                              "(keying story) with every merge decided by a human"}
        return {"id": entry["id"], "verdict": "swallowed",
                "detail": "no keying story / merge policy in the spec"}
    for subject, predicate in check["subjects"]:
        if _unknown_for(spec, subject, predicate):
            return {"id": entry["id"], "verdict": "routed-to-runtime-question",
                    "detail": f"{subject} {predicate} is an unresolved dispute in the spec"}
        rule = _rule_for(spec, subject, predicate)
        if rule is None:
            continue
        value = rule.get("value")
        text = value if isinstance(value, str) else ""
        if (subject, predicate) == ("identity", "keying_story") \
                and isinstance(value, dict):
            position = _keying_position(value)
            if position == "false":
                return {"id": entry["id"], "verdict": "swallowed",
                        "detail": f"spec adopted the false position "
                                  f"({check.get('false')!r})"}
            if position == "truth":
                return {"id": entry["id"], "verdict": _caught_by(rule),
                        "detail": f"spec carries the true position via "
                                  f"{rule['provenance']['kind']}"}
            return {"id": entry["id"], "verdict": "swallowed",
                    "detail": f"spec value {value!r} matches neither position"}
        if "truth_value" in check:
            if value == check["truth_value"]:
                return {"id": entry["id"], "verdict": _caught_by(rule),
                        "detail": f"spec value {value!r} via {rule['provenance']['kind']}"}
            if value == check.get("false_value"):
                return {"id": entry["id"], "verdict": "swallowed",
                        "detail": f"spec adopted the false value {value!r}"}
        else:
            if check.get("false") and check["false"] in text:
                return {"id": entry["id"], "verdict": "swallowed",
                        "detail": f"spec adopted the false position ({check['false']!r})"}
            if check.get("truth") and check["truth"] in text:
                return {"id": entry["id"], "verdict": _caught_by(rule),
                        "detail": f"spec carries the true position via "
                                  f"{rule['provenance']['kind']}"}
        return {"id": entry["id"], "verdict": "swallowed",
                "detail": f"spec value {value!r} matches neither position"}
    # No rule and no known unknown: the fact was never handled at all.
    # Absence is a miss, not a routed question — "routed" requires an
    # explicit unknown/routing artifact in the spec.
    return {"id": entry["id"], "verdict": "missed",
            "detail": "no rule and no unknown recorded for the checked subjects"}


def grade(discrepancies: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [grade_entry(e, spec) for e in discrepancies]


def summarize(verdicts: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in verdicts:
        out[v["verdict"]] = out.get(v["verdict"], 0) + 1
    return out
