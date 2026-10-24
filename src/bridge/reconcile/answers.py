"""Answering reconciliation questions: answer -> mapping rule -> release/requeue affected records."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..runs import store as S

CLINICAL_KINDS = {"identity_match", "icd9_one_to_many", "retired_icd10", "unmapped_icd9", "unmapped_local_dx",
                  "missing_birth_date", "nka_conflict", "unmapped_medication", "unmapped_lab", "unparseable_sig"}


class AnswerError(ValueError):
    pass


def answer(store: S.RunStore, qid: str, option: str, value: str | None = None, answered_by: str = "user",
           rationale: str = "") -> dict[str, Any]:
    q = store.question(qid)
    if q["status"] == "answered":
        raise AnswerError(f"question {qid} is already answered")
    opt = next((o for o in q["options"] if o["key"] == option), None)
    if opt is None:
        raise AnswerError(f"option {option!r} not in {[o['key'] for o in q['options']]}")
    if opt.get("needs_value") and not value:
        raise AnswerError(f"option {option!r} requires a value")
    if answered_by.startswith("assistant") and (q["blocking"] or q["kind"] in CLINICAL_KINDS):
        raise AnswerError("assistant-authored answers are only allowed for non-blocking, non-clinical questions; ask the user")
    run_id = q["run_id"]
    decision = {"option": option, "value": value}
    store.answer_question(qid, {**decision, "answered_by": answered_by, "rationale": rationale,
                                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    rule_id = store.add_rule(run_id, q["kind"], q["match_key"], decision, answered_by, qid)

    if q["kind"] == "identity_match" and option == "same":
        _merge_identity(store, run_id, q)

    released = requeued = 0
    for a in q["affected"]:
        rec = store.record(run_id, a["rtype"], a["source_key"])
        if rec is None:
            continue
        if rec["status"] == S.HELD and rec["held_by"] == qid:
            store.update_record(run_id, a["rtype"], a["source_key"], status=S.PENDING, held_by=None, note=f"released by {qid}")
            released += 1
        elif a["used_default"] and option != q["default_option"] and rec["status"] in (S.LOADED, S.REJECTED):
            store.update_record(run_id, a["rtype"], a["source_key"], status=S.PENDING)
            requeued += 1
    store.event(run_id, "answer", {"question": qid, "kind": q["kind"], "option": option, "by": answered_by,
                                   "released": released, "requeued": requeued, "rule": rule_id})
    return {"question": qid, "rule": rule_id, "released": released, "requeued": requeued}


def _merge_identity(store: S.RunStore, run_id: str, q: dict[str, Any]) -> None:
    surv_key, dup_key = q["context"]["candidate_patient"], q["context"]["this_patient"]
    # follow earlier merges
    while store.status_of(run_id, "Patient", surv_key) == S.SUPERSEDED:
        surv_key = store.xget(run_id, "superseded", f"Patient/{surv_key}")
    dup, surv = store.record(run_id, "Patient", dup_key), store.record(run_id, "Patient", surv_key)
    if dup["status"] == S.LOADED:
        raise AnswerError(f"{dup_key} was already loaded as a separate patient; use merge_patients instead")
    src, extra = surv["source"], dup["source"]
    src["members"] += extra["members"]
    src["links"].update({m["PAT_ID"]: "user-confirmed" for m in extra["members"]})
    src["a08"].update(extra.get("a08", {}))
    src["aliases"] += extra.get("aliases", [])
    src["has_allergy_rows"] = src["has_allergy_rows"] or extra["has_allergy_rows"]
    src["review"] = [r for r in src.get("review", []) if r["other"] != dup_key]
    new_status = surv["status"] if surv["status"] in (S.HELD, S.BLOCKED) else S.PENDING
    store.update_record(run_id, "Patient", surv_key, source=src, status=new_status)
    store.update_record(run_id, "Patient", dup_key, status=S.SUPERSEDED, note=f"merged into {surv_key} by user", held_by=None)
    store.xset(run_id, "superseded", f"Patient/{dup_key}", surv_key)
    for m in extra["members"]:
        store.xset(run_id, "pat", m["PAT_ID"], surv_key)
