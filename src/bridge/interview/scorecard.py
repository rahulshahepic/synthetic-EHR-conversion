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
                                        "false": "one account per patient",
                                        "keying_truth": {"account_field": "ACCT",
                                                         "min_departments": 2}},
    "belief_lab_account_is_identity": {"subjects": [("identity", "keying_story")],
                                       "truth": "Departmental accounts",
                                       "false": "L number is the patient",
                                       "keying_truth": {"account_field": "ACCT",
                                                        "min_departments": 2}},
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
    "disagreement_duplicate_charts": {"special": "duplicate_charts",
                                      "keying_truth": {"account_field": "ACCT",
                                                       "min_departments": 2}},
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


# Field names that make a key a cross-person demographic / person
# match — the position the graders treat as false, whatever its shape.
# Matched against every component of every token, composites included.
_DEMOGRAPHIC_FIELDS = {"SSN", "SSN4", "DOB", "NAME", "PATIENT_NAME", "MRN"}


def _keying_truth(check: dict[str, Any]) -> dict[str, Any] | None:
    """The check's recorded keying truth, or None when there is none
    to grade against: the key is missing, its value is not a dict (a
    hand-edited ``"ACCT/2"`` string), or a member has the wrong type
    (``account_field`` must be a non-empty string, ``min_departments``
    a positive int — ``"2"`` would crash the ``>=`` comparison). A
    malformed truth is "ungraded", never an exception that aborts
    grading for every discrepancy, and never a default."""
    truth = check.get("keying_truth")
    if not isinstance(truth, dict):
        return None
    account_field = truth.get("account_field")
    min_departments = truth.get("min_departments")
    if not isinstance(account_field, str) or not account_field:
        return None
    if not isinstance(min_departments, int) or isinstance(min_departments, bool) \
            or min_departments < 1:
        return None
    return truth


def _keying_position(value: dict[str, Any], check: dict[str, Any]) -> str | None:
    """The position a structured keying story takes, graded against the
    expected structured facts in the check data (``keying_truth``) — not
    shape alone. The true position: EVERY component of every key field
    is a per-department account reference (``<dept>.*.ACCT``), spanning
    at least ``min_departments`` distinct departments, with no master
    index. A composite token is split and checked part by part: it
    takes its field name from every part, not only the last, and its
    department from every part, not only the first — so
    ``LAB.TXT.MRN+REG.TXT.ACCT`` is not a lab account key. The false
    family: a master index, a single key treated as identity, or any
    demographic/person component (SSN, SSN4, DOB, NAME, PATIENT_NAME,
    MRN) anywhere in the story. ``master_index`` absent grades the
    same as False — the spec validator treats the flag as optional, so
    a departmental story without it is the true position, not neither.
    Anything else — unrelated fields, one department's keys alone, a
    mix of account and non-account fields — takes neither position.

    The truth is required, never defaulted: a check whose data lacks
    ``keying_truth`` (a missing or misspelled key in the grading data)
    grades as "ungraded", not against a silently assumed
    ACCT / 2-departments truth that would report a confident verdict
    computed from facts nobody recorded."""
    fields = value.get("key_fields") or []
    expected = _keying_truth(check)
    if expected is None:
        return "ungraded"
    account_field = expected["account_field"]
    min_departments = expected["min_departments"]
    if value.get("master_index") is True or len(fields) == 1:
        return "false"
    parts = [part for token in fields for part in str(token).split("+")]
    leaf_fields = [part.rsplit(".", 1)[-1] for part in parts]
    if any(leaf in _DEMOGRAPHIC_FIELDS for leaf in leaf_fields):
        return "false"
    if parts and all(leaf == account_field for leaf in leaf_fields):
        departments = {part.split(".")[0] for part in parts}
        if len(departments) >= min_departments:
            return "truth"
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
        # The truth check comes FIRST, before the spec is even looked
        # at: with no recorded keying_truth there is nothing to grade
        # against, whatever the spec does or does not contain — a
        # missing keying rule used to fall through to "swallowed",
        # a confident verdict computed from no truth at all.
        if _keying_truth(check) is None:
            return {"id": entry["id"], "verdict": "ungraded",
                    "detail": "check data carries no keying_truth for "
                              "this entry; refusing to grade against a "
                              "default truth"}
        keying = _rule_for(spec, "identity", "keying_story")
        policy = next((r for r in spec.get("rules", []) if r.get("id") == "SAFETY-IDENTITY-MERGE"),
                      None)
        if keying is not None and policy is not None:
            value = keying.get("value")
            # Routing requires BOTH the recorded resolved fact AND a
            # keying story that takes the true position: true_duplicates
            # recorded on top of a false keying story (a demographic
            # match key, a master index) resolves nothing — the story
            # itself is the false position wearing the fact as a badge.
            if isinstance(value, dict) and value.get("true_duplicates") is True \
                    and _keying_position(value, check) == "truth":
                return {"id": entry["id"], "verdict": "routed-to-runtime-question",
                        "detail": "the disagreement resolves into per-person matching "
                                  "(keying story, true duplicate charts recorded) "
                                  "with every merge decided by a human"}
            return {"id": entry["id"], "verdict": "swallowed",
                    "detail": "the spec's keying story does not record the resolved "
                              "fact (registration creates true duplicate charts) "
                              "on a true-position keying story, "
                              "so the resolution is not fully recorded"}
        return {"id": entry["id"], "verdict": "swallowed",
                "detail": "no keying story / merge policy in the spec"}
    if ("identity", "keying_story") in check["subjects"] \
            and _keying_truth(check) is None:
        # Same truth-first rule as duplicate_charts: a keying check with
        # no usable keying_truth is ungraded whatever the spec holds,
        # including no keying rule at all (which would otherwise fall
        # through to a confident "missed").
        return {"id": entry["id"], "verdict": "ungraded",
                "detail": "check data carries no keying_truth for "
                          "this entry; refusing to grade against a "
                          "default truth"}
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
            position = _keying_position(value, check)
            if position == "ungraded":
                return {"id": entry["id"], "verdict": "ungraded",
                        "detail": "check data carries no keying_truth for "
                                  "this entry; refusing to grade against a "
                                  "default truth"}
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
