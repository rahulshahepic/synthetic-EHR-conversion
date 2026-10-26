"""Post-execution scoring, intentionally separate from discovery/conversion.

Reads fixture truth and actual Nimbus API snapshots. Expected dispositions
are calculated independently of adapter functions and mapper outputs. This
does not make a same-author fixture a blinded evaluation.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


def grade(root: Path, label="corrected") -> dict:
    truth = json.loads((root / "source/grading/truth.json").read_text())
    snapshot = json.loads((root / (label + "_target.json")).read_text())
    record_list = json.loads((root / (label + "_records.json")).read_text())
    records = {rt: {r["source_key"]: r for r in rows} for rt, rows in record_list.items()}
    targets = {rt: {r["sourceKey"]: r for r in rows} for rt, rows in snapshot.items()}
    errors, checks = [], Counter()
    def check(ok, name, key, want=None, got=None):
        checks[name] += 1
        if not ok: errors.append({"check": name, "key": key, "expected": want, "actual": got})
    def compare(got, want, name, key): check(got == want, name, key, want, got)
    def status(rt, key, want):
        got = records[rt].get(key, {}).get("status")
        compare(got, want, "record_disposition", rt + "/" + key)
        compare(key in targets[rt], want == "loaded", "target_presence", rt + "/" + key)
        return targets[rt].get(key) if want == "loaded" else None
    def pat_available(key): return truth["patients"][key]["dob"] is not None
    def parent(got, patkey, key): compare(got.get("patient", {}).get("sourceKey"), "Patient/" + patkey, "patient_identity_reference", key)
    def utc(got, want, key):
        compare(datetime.fromisoformat(got), datetime.fromisoformat(want), "clinical_timestamp", key)
    for key, p in truth["patients"].items():
        got = status("Patient", key, "loaded" if p["dob"] else "held")
        if got:
            compare(got["birthDate"], datetime.strptime(p["dob"], "%Y%m%d").date().isoformat(), "birth_date", key)
            compare(got["noKnownAllergies"], p["nka"], "nka_conflict", key)
            compare(got["identifiers"], [{"system": "urn:briar:" + key.split("|")[0] + ":chart", "value": key.split("|")[1]}], "scoped_identifier", key)
    for key, v in truth["visits"].items():
        want = "held" if v["utc"] is None else "loaded" if pat_available(v["patient"]) else "blocked"
        got = status("Encounter", key, want)
        if got:
            parent(got, v["patient"], key)
            utc(got["period"]["start"], v["utc"], key)
    for key, lab in truth["labs"].items():
        if lab["deleted_accession"] or lab["result"] == "999999": want = "dropped"
        elif key.endswith("|GLU") and not lab["unit"]: want = "held"
        elif not pat_available(lab["patient"]): want = "blocked"
        else: want = "loaded"
        got = status("Observation", key, want)
        if got:
            parent(got, lab["patient"], key)
            utc(got["effective"], lab["utc"], key)
            compare(got["status"], lab["status"], "latest_lab_revision", key)
            if lab["result"] == "NEG": compare(got.get("valueCodeable"), "negative", "qualitative_result", key)
            else:
                # Independent lexical split: comparison, suffix, numeric body.
                raw = lab["result"]
                suffix = raw[-1] if raw[-1] in "HL" else ""
                body = raw[:-1] if suffix else raw
                comparator = body[0] if body[0] in "<>" else None
                value = float(body[1:] if comparator else body)
                compare(got.get("valueQuantity", {}).get("value"), value, "lab_numeric_value", key)
                compare(got.get("valueQuantity", {}).get("unit"), lab["unit"], "lab_unit", key)
                compare(got.get("valueQuantity", {}).get("comparator"), comparator, "lab_comparator", key)
                compare(got.get("interpretation"), {"H": "high", "L": "low"}.get(suffix), "lab_flag", key)
    for key, med in truth["meds"].items():
        want = "held" if med["drug"] == "MISC" else "loaded" if pat_available(med["patient"]) else "blocked"
        got = status("MedicationRequest", key, want)
        if got:
            parent(got, med["patient"], key)
            compare(got["status"], med["status"], "medication_status", key)
            compare(got["medication"]["coding"][0]["code"], "860975", "drug_mapping", key)
            compare(got["dosage"].get("text"), "TAKE ONE TABLET BY MOUTH TWICE DAILY", "sig_preservation", key)
            compare(got["dosageStructured"], False, "sig_not_falsely_structured", key)
    for key, dx in truth["diagnoses"].items():
        got = status("Condition", key, "loaded" if pat_available(dx["patient"]) else "blocked")
        if got:
            parent(got, dx["patient"], key)
            compare(got["code"].get("text"), dx["text"], "diagnosis_text", key)
            if dx["code"] == "HXD":
                compare(got["code"].get("coding", []), [], "no_invented_diagnosis", key)
                compare(got["verificationStatus"], "unconfirmed", "uncoded_diagnosis_flagged", key)
            else: compare(got["code"]["coding"][0]["code"], "E11.9", "diagnosis_mapping", key)
    for key, allergy in truth["allergies"].items():
        got = status("AllergyIntolerance", key, "loaded" if pat_available(key) else "blocked")
        if got:
            parent(got, key, key)
            substance, reaction = allergy.split(":")
            compare(got["substance"].get("text"), substance, "allergy_substance", key)
            compare(got["reactions"][0]["manifestation"].get("text"), reaction, "allergy_reaction", key)
            compare(got["criticality"], "unable-to-assess", "no_invented_allergy_severity", key)
    for key, note in truth["notes"].items():
        got = status("DocumentReference", key, "loaded" if pat_available(note["patient"]) else "blocked")
        if got:
            parent(got, note["patient"], key)
            compare(got["content"], note["text"], "note_bytes_and_order", key)
    for key, appt in truth["appointments"].items():
        want = "held" if appt["status"] is None else "loaded" if pat_available(appt["patient"]) else "blocked"
        got = status("Appointment", key, want)
        if got:
            parent(got, appt["patient"], key)
            compare(got["status"], appt["status"], "appointment_status", key)
            utc(got["start"], "2026-10-20T19:00:00+00:00", key)
            utc(got["end"], "2026-10-20T19:30:00+00:00", key)
    for key, charge in truth["charges"].items():
        visit = truth["visits"][charge["visit"]]
        want = "held" if charge["amount"] < 0 else "loaded" if pat_available(charge["patient"]) and visit["utc"] else "blocked"
        got = status("ChargeItem", key, want)
        if got:
            parent(got, charge["patient"], key)
            compare(got["amount"], charge["amount"], "charge_scale_and_sign", key)
            compare(got["encounter"]["sourceKey"], "Encounter/" + charge["visit"], "charge_visit_reference", key)
    expected_sizes = {"Patient": len(truth["patients"]), "Encounter": len(truth["visits"]), "Observation": len(truth["labs"]), "MedicationRequest": len(truth["meds"]),
        "Condition": len(truth["diagnoses"]), "AllergyIntolerance": len(truth["allergies"]), "DocumentReference": len(truth["notes"]), "Appointment": len(truth["appointments"]), "ChargeItem": len(truth["charges"])}
    for rt, n in expected_sizes.items():
        compare(len(records[rt]), n, "logical_record_count", rt)
        compare(sorted(targets[rt]), sorted(k for k, r in records[rt].items() if r["status"] == "loaded"), "target_key_set", rt)
    result = {"label": label, "ok": not errors, "checks": dict(checks), "checks_total": sum(checks.values()), "errors": errors,
              "scope": "Every logical record disposition and target presence, every loaded clinical identity/reference and listed field; actual API snapshots, not Bridge mapped payloads. Same-author fixture, not blinded."}
    (root / (label + "_grade.json")).write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def canonical(snapshot):
    def clean(x):
        if isinstance(x, list): return [clean(v) for v in x]
        if isinstance(x, dict): return {k: clean(v) for k, v in x.items() if k not in ("id", "meta", "provenance")}
        return x
    return clean(snapshot)
