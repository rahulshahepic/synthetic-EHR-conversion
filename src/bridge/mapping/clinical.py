"""Mappers: MedicationRequest, Observation (labs + vitals), Immunization, DocumentReference,
Appointment, ChargeItem, UserAccount."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from ..normalize import demographics as demo
from ..normalize.sig import parse_sig
from ..normalize.time import parse_date8
from ..normalize.units import normalize_unit, parse_reference_range, parse_result_value
from .base import MapContext, mapper
from .core import _zoned, location_key

# ----------------------------------------------------------------------------- medications
MED_STATUS = {"A": "active", "D": "stopped", "C": "completed", "H": "on-hold"}
DOSE_UNITS = {"MG": "mg", "MCG": "ug", "ML": "mL", "UNITS": "[iU]", "UNIT": "[iU]", "TAB": "{tab}", "TABS": "{tab}",
              "CAP": "{cap}", "PUFFS": "{puff}", "PUFF": "{puff}"}


def _dose(raw: str) -> tuple[float, str] | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?|\d+/\d+)\s*([A-Za-z]+)\s*", raw or "")
    if not m or m.group(2).upper() not in DOSE_UNITS:
        return None
    v = m.group(1)
    value = float(v.split("/")[0]) / float(v.split("/")[1]) if "/" in v else float(v)
    return value, DOSE_UNITS[m.group(2).upper()]


@mapper("MedicationRequest")
def map_medication(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    hit = ctx.terms.formulary.get(s["FORM_CODE"])
    if hit:
        med = {"coding": [{"system": "RxNorm", "code": hit[0], "display": hit[1]}], "text": s["DRUG_NAME"]}
        ctx.note("medication", "standardized", 4.0)
    else:
        d = ctx.decide(
            "unmapped_medication", s["FORM_CODE"],
            f"Halcyon formulary item {s['FORM_CODE']} ({s['DRUG_NAME']}) has no RxNorm mapping; Nimbus requires RxNorm. "
            "Provide an RxNorm code, or leave these orders out (they will be listed for pharmacist medication reconciliation).",
            [{"key": "rxnorm", "label": "Use RxNorm code (enter it)", "needs_value": True},
             {"key": "exclude", "label": "Do not convert; list for medication reconciliation"}],
            blocking=True, context={"form_code": s["FORM_CODE"], "drug_name": s["DRUG_NAME"], "example_sig": s["SIG"]})
        if d is None:
            return None
        if d["option"] == "exclude" or not re.fullmatch(r"\d{2,8}", d.get("value") or ""):
            ctx.note("record", "dropped", 4.0, f"{s['DRUG_NAME']} excluded: no RxNorm (listed for med rec)", s["FORM_CODE"])
            return None
        med = {"coding": [{"system": "RxNorm", "code": d["value"]}], "text": s["DRUG_NAME"]}
        ctx.note("medication", "inferred", 4.0, "RxNorm supplied by user rule", s["FORM_CODE"])

    sig = parse_sig(s["SIG"])
    dosage: dict[str, Any] = {"text": s["SIG"]}
    dose = (sig.dose_value, sig.dose_unit) if sig.dose_value is not None else _dose(s["DOSE"])
    structured = sig.confidence >= 0.8 and dose is not None and sig.route is not None and (sig.frequency_count or sig.as_needed)
    if structured:
        dosage.update(doseQuantity={"value": dose[0], "unit": dose[1]}, route=sig.route, asNeeded=sig.as_needed)
        if sig.frequency_count:
            dosage["frequency"] = {"count": sig.frequency_count, "period": sig.frequency_period, "periodUnit": sig.frequency_period_unit}
        if sig.as_needed_reason:
            dosage["asNeededReason"] = sig.as_needed_reason
        if sig.duration_days:
            dosage["durationDays"] = sig.duration_days
        ctx.note("dosage", "transformed", 2.0)
    else:
        ctx.note("dosage", "degraded", 2.0, f"sig not fully parsed (confidence {sig.confidence}; unparsed '{sig.unparsed}'); kept as text", s["SIG"])
    status = MED_STATUS.get(s["STATUS"].strip(), "unknown")
    ctx.note("status", "standardized" if s["STATUS"].strip() in MED_STATUS else "defaulted", 1.0)
    authored = parse_date8(s["START_DT"])
    if authored is None:
        ctx.note("record", "dropped", 1.0, "no start date", s["START_DT"])
        return None
    out: dict[str, Any] = {"patient": patient, "medication": med, "status": status, "authoredOn": authored.isoformat(),
                           "dosage": dosage, "dosageStructured": bool(structured)}
    if s["STOP_DT"]:
        ctx.note("stopDate", "dropped", 0.3, "Nimbus MedicationRequest has no stop date (duration kept if parsed)", s["STOP_DT"])
    enc = ctx.optional("Encounter", s["VISIT_ID"], "encounter")
    if enc:
        out["encounter"] = enc
    pr = ctx.optional("Practitioner", s["PROV_ID"], "prescriber")
    if pr:
        out["prescriber"] = pr
    return out


# ----------------------------------------------------------------------------- observations
VITALS = {  # field -> (loinc, display)
    "PULSE": ("8867-4", "Heart rate", "/min"), "RESP": ("9279-1", "Respiratory rate", "/min"),
    "TEMP": ("8310-5", "Body temperature", None), "WT": ("29463-7", "Body weight", None),
    "HT": ("8302-2", "Body height", None), "SPO2": ("59408-5", "Oxygen saturation", "%"),
}
PLAUSIBLE = {"/min": (2, 300), "%": (40, 100), "[degF]": (77, 113), "Cel": (25, 45), "kg": (0.2, 700),
             "[lb_av]": (0.5, 1500), "cm": (20, 275), "[in_i]": (8, 108), "mm[Hg]": (20, 300)}
INTERP = {"H": "high", "L": "low", "A": "abnormal", "HH": "critical-high", "LL": "critical-low", "N": "normal"}


def _plausible(value: float, unit: str) -> bool:
    lo, hi = PLAUSIBLE.get(unit, (float("-inf"), float("inf")))
    return lo <= value <= hi


def _implausible(ctx: MapContext, field: str, raw: str, unit: str) -> float | None:
    d = ctx.decide(
        "implausible_vital", field,
        f"Some Halcyon {field} vital-sign values are physiologically implausible (e.g. {raw!r} {unit}); Nimbus rejects them. "
        "Drop them, or attempt the common typo correction (missing decimal point: divide by 10)?",
        [{"key": "drop", "label": "Drop implausible values (kept in the loss ledger)"},
         {"key": "div10", "label": "Divide by 10 when that makes the value plausible, otherwise drop"}],
        blocking=False, default="drop", context={"field": field, "example": raw, "unit": unit})
    if d["option"] == "div10":
        v = float(raw) / 10
        if _plausible(v, unit):
            ctx.note("valueQuantity", "inferred", 2.0, f"implausible {raw} corrected to {v} (decimal typo rule)", raw)
            return v
    ctx.note("record", "dropped", 2.0, f"implausible {field} value {raw} {unit}", raw)
    return None


@mapper("Observation")
def map_observation(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    out: dict[str, Any] = {"patient": patient}
    if s.get("VISIT_ID"):
        enc = ctx.optional("Encounter", s["VISIT_ID"], "encounter")
        if enc:
            out["encounter"] = enc
    return _vital(ctx, s, out) if s["kind"] == "vital" else _lab(ctx, s, out)


def _vital(ctx: MapContext, s: dict[str, Any], out: dict[str, Any]) -> dict[str, Any] | None:
    f, raw = s["FIELD"], s["VALUE"].strip()
    eff = _zoned(ctx, s["TAKEN_DT"], s["_PAT_FAC"], "effective", 0.5)
    if eff is None:
        ctx.note("record", "dropped", 1.0, "no measurement time", s["TAKEN_DT"])
        return None
    out.update(category="vital-signs", effective=eff.isoformat())
    if f == "BP":
        m = re.fullmatch(r"(\d{2,3})\s*/\s*(\d{2,3})", raw)
        if not m:
            ctx.note("record", "dropped", 2.0, f"malformed blood pressure {raw!r}", raw)
            return None
        sys_, dia = float(m.group(1)), float(m.group(2))
        if not (_plausible(sys_, "mm[Hg]") and _plausible(dia, "mm[Hg]")):
            ctx.note("record", "dropped", 2.0, f"implausible blood pressure {raw}", raw)
            return None
        out["code"] = {"coding": [{"system": "LOINC", "code": "85354-9", "display": "Blood pressure panel"}]}
        out["components"] = [
            {"code": {"coding": [{"system": "LOINC", "code": "8480-6"}]}, "valueQuantity": {"value": sys_, "unit": "mm[Hg]"}},
            {"code": {"coding": [{"system": "LOINC", "code": "8462-4"}]}, "valueQuantity": {"value": dia, "unit": "mm[Hg]"}}]
        ctx.note("components", "transformed", 2.0)
        return out
    loinc, display, fixed_unit = VITALS[f]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([A-Za-z]+)?", raw)
    if not m:
        ctx.note("record", "dropped", 2.0, f"unparseable {f} value {raw!r}", raw)
        return None
    value = float(m.group(1))
    if fixed_unit:
        unit = fixed_unit
        ctx.note("valueQuantity.unit", "exact", 1.0)
    elif m.group(2) and normalize_unit(m.group(2)):
        unit = normalize_unit(m.group(2))
        ctx.note("valueQuantity.unit", "transformed", 1.0, "unit embedded in value text")
    else:
        unit = ctx.profile.VITAL_UNITS.get(s["_PAT_FAC"], {}).get(f)
        if unit is None:
            ctx.note("record", "dropped", 2.0, f"no unit convention for facility {s['_PAT_FAC']}", raw)
            return None
        ctx.note("valueQuantity.unit", "inferred", 1.0, f"unit {unit} inferred from facility {s['_PAT_FAC']} convention")
    if not _plausible(value, unit):
        fixed = _implausible(ctx, f, m.group(1), unit)
        if fixed is None:
            return None
        value = fixed
    else:
        ctx.note("valueQuantity", "exact", 2.0)
    out["code"] = {"coding": [{"system": "LOINC", "code": loinc, "display": display}]}
    out["valueQuantity"] = {"value": value, "unit": unit}
    return out


def _lab(ctx: MapContext, s: dict[str, Any], out: dict[str, Any]) -> dict[str, Any] | None:
    code = s["TEST_CODE"]
    hit = ctx.terms.labs.get(code)
    if hit is None:
        d = ctx.decide(
            "unmapped_lab", code,
            f"Halcyon lab test {code} ({s['TEST_NAME']}) has no LOINC mapping; Nimbus requires LOINC. Provide a LOINC code, "
            "or leave these results out (they remain in the legacy archive).",
            [{"key": "loinc", "label": "Use LOINC code (enter it)", "needs_value": True},
             {"key": "exclude", "label": "Do not convert these results"}],
            blocking=True, context={"test_code": code, "test_name": s["TEST_NAME"], "example_value": s["RESULT_VAL"]})
        if d is None:
            return None
        if d["option"] == "exclude" or not re.fullmatch(r"\d{1,5}-\d", d.get("value") or ""):
            ctx.note("record", "dropped", 3.0, f"lab {code} excluded by rule", code)
            return None
        hit = (d["value"], "", s["TEST_NAME"])
        ctx.note("code", "inferred", 3.0, "LOINC supplied by user rule", code)
    else:
        ctx.note("code", "standardized", 3.0)
    loinc, ucum, display = hit
    eff = _zoned(ctx, s["COLLECT_DT"], s["_PAT_FAC"], "effective", 0.5)
    if eff is None:
        ctx.note("record", "dropped", 1.0, "no collection time", s["COLLECT_DT"])
        return None
    out.update(category="laboratory", code={"coding": [{"system": "LOINC", "code": loinc, "display": display}], "text": s["TEST_NAME"]},
               effective=eff.isoformat(), status="corrected" if s.get("_STATUS") == "C" else "final", accession=s.get("ACCESSION"))
    if s.get("_corrected_from") is not None:
        ctx.note("value", "exact", 2.0, f"corrected result from ORU feed replaced {s['_corrected_from']}")
    pv = parse_result_value(s["RESULT_VAL"])
    if pv.kind == "quantity":
        src_unit = normalize_unit(s["UNITS"]) if s["UNITS"] else None
        unit = ucum or src_unit
        if not unit:
            out["valueString"] = s["RESULT_VAL"]
            ctx.note("value", "degraded", 2.0, "numeric result without a known unit kept as text", s["RESULT_VAL"])
        else:
            if src_unit and ucum and src_unit != ucum:
                ctx.note("valueQuantity.unit", "dropped", 2.0, f"source unit {s['UNITS']} differs from expected {ucum}", s["UNITS"])
                out["valueString"] = f"{s['RESULT_VAL']} {s['UNITS']}"
            else:
                q: dict[str, Any] = {"value": pv.value, "unit": unit}
                if pv.comparator:
                    q["comparator"] = pv.comparator
                out["valueQuantity"] = q
                ctx.note("valueQuantity", "transformed" if src_unit or not s["UNITS"] else "standardized", 2.0)
    elif pv.kind == "coded":
        out["valueCodeable"] = pv.code
        ctx.note("value", "standardized", 2.0)
    else:
        out["valueString"] = s["RESULT_VAL"] or "(blank)"
        ctx.note("value", "degraded", 2.0, f"non-numeric result {s['RESULT_VAL']!r} kept as text", s["RESULT_VAL"])
    if s["REF_RANGE"]:
        lo, hi = parse_reference_range(s["REF_RANGE"])
        rr: dict[str, Any] = {"text": s["REF_RANGE"]}
        if lo is not None:
            rr["low"] = lo
        if hi is not None:
            rr["high"] = hi
        out["referenceRange"] = rr
    flag = s["ABN_FLAG"].strip().upper()
    if flag in INTERP:
        out["interpretation"] = INTERP[flag]
    return out


# ----------------------------------------------------------------------------- immunization
@mapper("Immunization")
def map_immunization(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    hit = ctx.terms.vaccines.get(s["VACCINE_CODE"])
    if hit is None:
        d = ctx.decide(
            "unmapped_vaccine", s["VACCINE_CODE"],
            f"Halcyon immunization code {s['VACCINE_CODE']} ({s['VACCINE_NAME']}) has no CVX code. If it is not a vaccine "
            "(e.g. a TB skin test) it has no place in Nimbus Immunization.",
            [{"key": "exclude", "label": "Do not convert (kept in the loss ledger)"},
             {"key": "cvx", "label": "Use CVX code (enter it)", "needs_value": True}],
            blocking=False, default="exclude", context={"code": s["VACCINE_CODE"], "name": s["VACCINE_NAME"]})
        if d["option"] != "cvx" or not re.fullmatch(r"\d{1,3}", d.get("value") or ""):
            ctx.note("record", "dropped", 2.0, f"{s['VACCINE_NAME']} not a CVX vaccine", s["VACCINE_CODE"])
            return None
        hit = (d["value"], s["VACCINE_NAME"])
    ctx.note("vaccine", "standardized" if s["VACCINE_CODE"] != hit[0] else "exact", 2.0)
    when = parse_date8(s["ADMIN_DT"])
    if when is None:
        ctx.note("record", "dropped", 1.0, "no administration date", s["ADMIN_DT"])
        return None
    reg = s.get("_REGISTRY")
    if reg:
        reg_date = reg["ADMIN_DATE"]
        if reg_date != when.strftime("%m/%d/%Y"):
            ctx.note("occurrenceDate", "inferred", 1.0, f"state registry reports {reg_date}; Halcyon date kept (authoritative)", reg_date)
        else:
            ctx.note("occurrenceDate", "exact", 1.0, "confirmed by state registry")
    else:
        ctx.note("occurrenceDate", "exact" if s["source"] == "db" else "transformed", 1.0,
                 None if s["source"] == "db" else "registry-only immunization added")
    out: dict[str, Any] = {"patient": patient, "vaccine": {"coding": [{"system": "CVX", "code": hit[0], "display": hit[1]}]},
                           "occurrenceDate": when.isoformat()}
    if s.get("LOT"):
        out["lotNumber"] = s["LOT"]
    if ctx.dedupe(ctx.patient_key(s["PAT_ID"]) or s["PAT_ID"], f"{hit[0]}:{when.isoformat()}"):
        return None
    return out


# ----------------------------------------------------------------------------- notes
def rtf_to_text(rtf: str) -> str:
    t = re.sub(r"\\par[d]?\b ?", "\n", rtf)
    t = re.sub(r"\\[a-z]+-?\d* ?", "", t)
    t = t.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s+", "\n", t)).strip()


@mapper("DocumentReference")
def map_note(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    ntype = ctx.terms.note_types.get(s["NOTE_TYPE"])
    if ntype is None:
        ntype = ("34109-9", "Note")
        ctx.note("type", "defaulted", 0.5, f"note type {s['NOTE_TYPE']} unmapped; generic note", s["NOTE_TYPE"])
    else:
        ctx.note("type", "standardized", 0.5)
    raw = s["NOTE_TEXT"]
    text = rtf_to_text(raw) if raw.lstrip().startswith("{\\rtf") else raw
    if text != raw:
        ctx.note("content.formatting", "dropped", 0.5, "RTF formatting (bold/italic) removed")
    if len(raw) >= 65535:
        text += "\n\n[Converted note: truncated at 65,535 characters in the legacy system; the remainder is unrecoverable.]"
        ctx.note("content", "degraded", 3.0, "note was truncated in Halcyon (64 KB limit)", len(raw))
    else:
        ctx.note("content", "transformed", 3.0)
    when = _zoned(ctx, s["NOTE_DT"], s["_PAT_FAC"], "date", 0.5)
    if when is None:
        ctx.note("record", "dropped", 1.0, "no note date", s["NOTE_DT"])
        return None
    out: dict[str, Any] = {"patient": patient, "type": {"coding": [{"system": "LOINC", "code": ntype[0], "display": ntype[1]}]},
                           "date": when.isoformat(), "contentType": "text/plain", "content": text}
    enc = ctx.optional("Encounter", s["VISIT_ID"], "encounter")
    if enc:
        out["encounter"] = enc
    au = ctx.optional("Practitioner", s["AUTHOR_PROV_ID"], "author")
    if au:
        out["author"] = au
    return out


# ----------------------------------------------------------------------------- appointments
APPT_STATUS = {"S": "booked", "C": "fulfilled", "N": "noshow", "A": "arrived", "X": "cancelled"}


@mapper("Appointment")
def map_appointment(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    code = s["STATUS"].strip()
    siu = s.get("_SIU")
    if siu and siu["status"].lower() == "cancelled":
        status = "cancelled"
        ctx.note("status", "exact", 1.0, "cancellation from newer SIU^S15 message", code)
    elif code in APPT_STATUS:
        status = APPT_STATUS[code]
        ctx.note("status", "standardized", 1.0)
    else:
        d = ctx.decide(
            "unrepresentable_appt_status", code or "(blank)",
            f"Halcyon appointment status {code!r} ('B' = bumped by the clinic) has no Nimbus equivalent. Bridge loads these as "
            "'cancelled' (the fact that the clinic, not the patient, cancelled is lost). Accept?",
            [{"key": "cancelled", "label": "Load as cancelled"}, {"key": "exclude", "label": "Do not convert these appointments"}],
            blocking=False, default="cancelled", context={"status": code})
        if d["option"] == "exclude":
            ctx.note("record", "dropped", 1.0, f"appointment status {code} excluded", code)
            return None
        status = "cancelled"
        ctx.note("status", "degraded", 1.0, f"status {code} (bumped) loaded as cancelled", code)
    fac = s["_PAT_FAC"]
    start = _zoned(ctx, s["APPT_DT"], fac, "start", 0.5)
    if start is None:
        ctx.note("record", "dropped", 1.0, "no appointment time", s["APPT_DT"])
        return None
    minutes = int(s["DURATION_MIN"]) if s["DURATION_MIN"].isdigit() and int(s["DURATION_MIN"]) > 0 else 15
    out: dict[str, Any] = {"patient": patient, "status": status, "start": start.isoformat(),
                           "end": (start + timedelta(minutes=minutes)).isoformat()}
    if s["REASON"]:
        out["reason"] = s["REASON"]
    pr = ctx.optional("Practitioner", s["PROV_ID"], "practitioner")
    if pr:
        out["practitioner"] = pr
    loc = ctx.optional("Location", location_key(ctx, s["DEPT_ID"], fac, fac), "location")
    if loc:
        out["location"] = loc
    return out


# ----------------------------------------------------------------------------- charges
@mapper("ChargeItem")
def map_charge(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    encounter = ctx.require("Encounter", s["VISIT_ID"])
    if encounter is None and ctx.resolve_key("Encounter", s["VISIT_ID"])[1] == "dropped":
        ctx.blocked_by = None
        ctx.note("record", "dropped", 1.0, "its encounter was not converted", s["VISIT_ID"])
        return None
    cdm = s.get("_CDM") or {}
    code = (cdm.get("CPT_HCPCS") or "").strip()
    if not code:
        d = ctx.decide(
            "unmapped_charge", s["CHG_CODE"],
            f"Charge code {s['CHG_CODE']} ({cdm.get('DESCRIPTION', 'not in charge master')}) has no CPT/HCPCS in the charge "
            "master. Nimbus charges must be CPT/HCPCS coded.",
            [{"key": "exclude", "label": "Do not convert (historical charge; kept in loss ledger)"},
             {"key": "code", "label": "Use CPT/HCPCS code (enter it)", "needs_value": True}],
            blocking=False, default="exclude", context={"code": s["CHG_CODE"], "description": cdm.get("DESCRIPTION")})
        if d["option"] != "code" or not d.get("value"):
            ctx.note("record", "dropped", 2.0, f"charge {s['CHG_CODE']} has no CPT/HCPCS", s["CHG_CODE"])
            return None
        code = d["value"].strip().upper()
        ctx.note("code", "inferred", 2.0, "code supplied by user rule", s["CHG_CODE"])
    else:
        ctx.note("code", "exact" if code == s["CHG_CODE"] else "standardized", 2.0)
    system = "HCPCS" if code[:1].isalpha() else "CPT"
    post = parse_date8(s["POST_DT"])
    if post is None:
        ctx.note("record", "dropped", 1.0, "no posting/service date", s["POST_DT"])
        return None
    raw_amt = s["AMOUNT"].strip()
    try:
        amount = float(raw_amt) if post < ctx.profile.CHARGE_CENTS_FROM else int(raw_amt) / 100
    except ValueError:
        ctx.note("record", "dropped", 2.0, f"unparseable amount {raw_amt!r}", raw_amt)
        return None
    ctx.note("amount", "transformed", 2.0, "dollars" if post < ctx.profile.CHARGE_CENTS_FROM else "cents converted to dollars")
    mods = [m for m in re.split(r"[\s,]+", s["MODIFIERS"].strip()) if m]
    return {"patient": patient, "encounter": encounter, "code": {"coding": [{"system": system, "code": code}]},
            "modifiers": mods, "units": int(s["UNITS"] or 1), "amount": round(amount, 2),
            "serviceDate": post.isoformat()}


# ----------------------------------------------------------------------------- users
GENERIC = re.compile(r"^(FRONTDESK|NURSE|TEMP|ADMIN|REGISTRATION|LAB|SCHED|BILLING|TRIAGE|GUEST|TEST|SHARED)[_-]?\d*$", re.I)


@mapper("UserAccount")
def map_user(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    if GENERIC.match(s["USERNAME"]):
        d = ctx.decide(
            "generic_user_account", "generic",
            "Halcyon has shared/generic logins (e.g. FRONTDESK1). Nimbus requires every account to belong to one person. "
            "These accounts will not be converted; staff who used them need individual Nimbus accounts.",
            [{"key": "exclude", "label": "Do not convert generic accounts"}],
            blocking=False, default="exclude", context={"example": s["USERNAME"]})
        _ = d
        ctx.note("record", "dropped", 1.0, f"generic account {s['USERNAME']}", s["USERNAME"])
        return None
    name = demo.parse_name(s["FULL_NAME"])
    ctx.note("username", "exact", 1.0)
    out: dict[str, Any] = {"username": s["USERNAME"].lower(), "personName": {"family": name.family, "given": name.given},
                           "active": s["ACTIVE"].strip().upper() == "Y"}
    if s["PROV_ID"]:
        pr = ctx.optional("Practitioner", s["PROV_ID"], "practitioner")
        if pr:
            out["practitioner"] = pr
    return out
