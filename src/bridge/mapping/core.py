"""Mappers: Organization, Location, Practitioner, Payer, Plan, Patient, Coverage, Encounter,
Condition, AllergyIntolerance. Each annotates fidelity for every field it writes or drops."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..normalize import demographics as demo
from ..normalize.legacy import fix_mojibake, parse_crammed_address
from ..normalize.time import localize, parse_date8, parse_local
from .base import MapContext, mapper

ICD10_RE = re.compile(r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-Z]{1,4})?$")
ICD9_RE = re.compile(r"^(V\d{2}|E\d{3}|\d{3})(\.\d{1,2})?$")


def _yn(v: str) -> bool:
    return v.strip().upper() == "Y"


US_ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles",
            "America/Anchorage", "Pacific/Honolulu"]


def facility_context(ctx: MapContext, fac: str) -> dict[str, Any]:
    return {"facility": fac, "facility_name": ctx.store.xget(ctx.run_id, "meta", "facility_names", {}).get(fac),
            "source_documentation": ctx.store.xget(ctx.run_id, "meta", "manifest_notes", {})}


def _tz(ctx: MapContext, fac: str) -> str | None:
    """Facility time zone from the source profile; unknown facilities become a (grouped, blocking) question."""
    tz = ctx.profile.FACILITY_TZ.get(fac)
    if tz:
        return tz
    if not fac:
        return ctx.profile.DEFAULT_TZ
    d = ctx.decide(
        "facility_timezone", fac,
        f"Facility {fac} is not in Bridge's source profile. Halcyon stores local times without a UTC offset; "
        f"which time zone does {fac} chart in? (Every timestamp from this facility depends on the answer.)",
        [{"key": z, "label": z} for z in US_ZONES], blocking=True, context=facility_context(ctx, fac))
    return d["option"] if d else None


def _zoned(ctx: MapContext, raw: str, fac: str, field: str, weight: float = 1.0) -> datetime | None:
    naive = parse_local(raw)
    if naive is None:
        return None
    tz = _tz(ctx, fac)
    if tz is None:
        return None
    aware, flag = localize(naive, tz)
    if flag == "ambiguous":
        ctx.note(field, "inferred", weight, "DST fall-back hour is ambiguous; first occurrence assumed", raw)
    elif flag == "nonexistent":
        ctx.note(field, "inferred", weight, "time falls in DST spring-forward gap; shifted +1h", raw)
    else:
        ctx.note(field, "transformed", weight)
    return aware


# ----------------------------------------------------------------------------- organizations
@mapper("Organization")
def map_organization(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    if s["kind"] == "system":
        ctx.note("type", "inferred", 0.2, "system level synthesized: Halcyon has no enterprise org")
        ctx.note("name", "exact")
        return {"name": s["name"], "type": "system"}
    if s["kind"] == "site":
        ctx.note("name", "exact")
        ctx.note("type", "inferred", 0.2, "Halcyon facility treated as Nimbus site")
        return {"name": s["FAC_NAME"], "type": "site", "partOf": ctx.require("Organization", ctx.profile.SYSTEM_ORG["key"]),
                "identifiers": [{"system": "urn:halcyon:facility", "value": s["FAC_ID"]}]}
    # department
    name = s["DEPT_NAME"].title()
    if s["SHARED"]:
        d = ctx.decide(
            "shared_department", s["DEPT_ID"],
            f"Halcyon department {s['DEPT_ID']} ({s['DEPT_NAME']}) is shared by all facilities, but every Nimbus "
            f"department must belong to exactly one site. How should it be represented?",
            [{"key": "duplicate", "label": "Create one copy under every site (encounters attach to the patient's facility)"}]
            + [{"key": f, "label": f"Create it only under site {f}"}
               for f in ctx.store.xget(ctx.run_id, "meta", "facilities", list(ctx.profile.FACILITY_TZ))],
            blocking=True, context={"dept": s["DEPT_ID"], "name": s["DEPT_NAME"]})
        if d is None:
            return None
        if d["option"] != "duplicate" and d["option"] != s["SITE"]:
            ctx.note("record", "dropped", 1.0, f"shared dept kept only under {d['option']}")
            return None
        ctx.note("partOf", "inferred", 1.0, f"shared department placed under {s['SITE']}")
    else:
        ctx.note("partOf", "exact")
    ctx.note("name", "transformed")
    return {"name": name, "type": "department", "partOf": ctx.require("Organization", f"SITE-{s['SITE']}"),
            "identifiers": [{"system": "urn:halcyon:dept", "value": s["DEPT_ID"]}]}


@mapper("Location")
def map_location(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    dept = ctx.require("Organization", f"DEPT-{s['DEPT_ID']}@{s['SITE']}")
    if dept is None and ctx.resolve_key("Organization", f"DEPT-{s['DEPT_ID']}@{s['SITE']}")[1] == "dropped":
        ctx.blocked_by = None
        ctx.note("record", "dropped", 1.0, "department not created at this site")
        return None
    ctx.note("name", "transformed")
    ctx.note("record", "inferred", 0.2, "one Location synthesized per department (Halcyon has no locations)")
    return {"name": s["DEPT_NAME"].title(), "department": dept}


def location_key(ctx: MapContext, dept_id: str, dept_fac: str, pat_fac: str) -> str | None:
    if not dept_id:
        return None
    if dept_fac:
        return f"LOC-{dept_id}@{dept_fac}"
    rule = ctx.store.rule(ctx.run_id, "shared_department", dept_id)
    site = rule["option"] if rule and rule["option"] != "duplicate" else (pat_fac or "FAC1")
    return f"LOC-{dept_id}@{site}"


# ----------------------------------------------------------------------------- practitioners & payers
@mapper("Practitioner")
def map_practitioner(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    name = demo.parse_name(s["NAME"])
    ctx.note("name", "transformed", 1.0)
    spec = ctx.terms.specialties.get(ctx.terms.norm(s["SPECIALTY"]))
    if spec:
        ctx.note("specialty", "standardized")
    else:
        spec = "other"
        ctx.note("specialty", "degraded", 0.5, f"specialty text {s['SPECIALTY']!r} not mapped; set to other", s["SPECIALTY"])
    billing = _yn(s["BILLING_FLAG"])
    npi = s["NPI"].strip() or None
    from_luhn = npi is None or _npi_ok(npi)
    if npi and not from_luhn:
        ctx.note("npi", "dropped", 2.0, f"NPI {npi} fails check digit", npi)
        npi = None
    if billing and npi is None:
        d = ctx.decide(
            "billing_provider_without_npi", ctx.key,
            f"Provider {s['NAME']} ({ctx.key}) is a billing provider in Halcyon but has no valid NPI. Nimbus requires an NPI "
            "for billing practitioners. Provide the NPI, or load them as non-billing?",
            [{"key": "non_billing", "label": "Load as non-billing (charges they rendered will need a billing provider)"},
             {"key": "npi", "label": "I will provide the NPI", "needs_value": True}],
            blocking=False, default="non_billing", context={"provider": s, "npi_on_file": s["NPI"]})
        if d["option"] == "npi" and d.get("value") and _npi_ok(d["value"]):
            npi = d["value"]
            ctx.note("npi", "exact", 2.0, "NPI supplied by user")
        else:
            billing = False
            ctx.note("billing", "degraded", 1.0, "billing flag cleared: no valid NPI")
    else:
        ctx.note("npi", "exact" if npi else "defaulted", 2.0 if billing else 0.5)
    out = {"name": {"family": name.family, "given": name.given, "suffix": name.suffix},
           "specialty": spec, "billing": billing, "active": _yn(s["ACTIVE"]),
           "identifiers": [{"system": "urn:halcyon:provider", "value": s["PROV_ID"]}]}
    if npi:
        out["npi"] = npi
    if s["TERM_DT"]:
        ctx.note("termDate", "dropped", 0.2, "Nimbus Practitioner has no termination date", s["TERM_DT"])
    return out


def _npi_ok(npi: str) -> bool:
    if not re.fullmatch(r"\d{10}", npi):
        return False
    total = 0
    for i, d in enumerate(reversed([int(c) for c in "80840" + npi[:9]])):
        d = d * 2 if i % 2 == 0 else d
        total += d - 9 if d > 9 else d
    return (10 - total % 10) % 10 == int(npi[9])


@mapper("Payer")
def map_payer(ctx: MapContext) -> dict[str, Any]:
    ctx.note("name", "transformed")
    return {"name": ctx.src["PAYER_NAME"].title(), "identifiers": [{"system": "urn:halcyon:payer", "value": ctx.src["PAYER_ID"]}]}


@mapper("Plan")
def map_plan(ctx: MapContext) -> dict[str, Any]:
    ctx.note("name", "transformed")
    ctx.note("planType", "exact")
    return {"name": ctx.src["PLAN_NAME"].title(), "payer": ctx.require("Payer", ctx.src["PAYER_ID"]), "planType": ctx.src["PLAN_TYPE"]}


# ----------------------------------------------------------------------------- patient
SEX_MAP = {"M": "male", "F": "female", "U": "unknown"}


@mapper("Patient")
def map_patient(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    as_of = date.fromisoformat(ctx.store.run(ctx.run_id)["config"]["as_of"])
    for rv in s.get("review", []):
        d = ctx.decide(
            "identity_match", f"{rv['other']}|{ctx.key}",
            f"Are these two Halcyon charts the same person? (match score {rv['score']}, matched on {', '.join(rv['reasons'])})",
            [{"key": "same", "label": "Same person: merge into one Nimbus patient"},
             {"key": "different", "label": "Different people: keep separate"}],
            blocking=True, context={"charts": rv["pair"], "candidate_patient": rv["other"], "this_patient": ctx.key})
        if d is None:
            return None
        if d["option"] == "same":  # rule applied before the merge hook ran (e.g. imported); never load a known duplicate
            ctx.superseded_by = rv["other"]
            return None
    members = s["members"]
    p = next(m for m in members if m["PAT_ID"] == s["primary"])

    raw_name, fixed = fix_mojibake(p["PAT_NAME"])
    name = demo.parse_name(raw_name)
    ctx.note("name", "inferred" if fixed else "transformed", 2.0, "repaired mis-encoded characters" if fixed else None,
             p["PAT_NAME"] if fixed else None)
    if not name.family:
        ctx.note("name.family", "defaulted", 2.0, "no family name", p["PAT_NAME"])
        name = demo.Name("UNKNOWN", name.given, name.suffix)

    dob = demo.parse_legacy_date(p["DOB"], as_of)
    if dob.value is None:
        others = [demo.parse_legacy_date(m["DOB"], as_of).value for m in members if m is not p]
        others = [o for o in others if o]
        if others:
            dob = demo.DateParse(others[0], "day", True)
            ctx.note("birthDate", "inferred", 3.0, "DOB missing on primary chart; taken from linked chart", p["DOB"])
        else:
            d = ctx.decide(
                "missing_birth_date", ctx.key,
                f"Patient {raw_name} ({ctx.key}) has no valid date of birth in Halcyon ({p['DOB']!r}). Nimbus requires one.",
                [{"key": "value", "label": "I will provide the date of birth (YYYY-MM-DD)", "needs_value": True},
                 {"key": "placeholder", "label": "Use placeholder 1900-01-01 and flag for registration follow-up"},
                 {"key": "skip", "label": "Do not convert this patient"}],
                blocking=True, context={"chart": identity_summary(p)})
            if d is None:
                return None
            if d["option"] == "skip":
                ctx.note("record", "dropped", 1.0, "user chose not to convert (no DOB)")
                return None
            if d["option"] == "value":
                dob = demo.DateParse(date.fromisoformat(d["value"]), "day", False)
                ctx.note("birthDate", "exact", 3.0, "DOB supplied by user")
            else:
                dob = demo.DateParse(date(1900, 1, 1), "day", False)
                ctx.note("birthDate", "defaulted", 3.0, "placeholder DOB", p["DOB"])
    else:
        ctx.note("birthDate", "inferred" if dob.inferred else "transformed", 3.0,
                 "2-digit year century inferred" if dob.inferred else None, p["DOB"] if dob.inferred else None)

    sex_raw = p["SEX"].strip().upper()
    gender = None
    if sex_raw in ("M", "F"):
        sex = SEX_MAP[sex_raw]
        ctx.note("sexAtBirth", "standardized", 2.0)
    elif sex_raw in ("U", ""):
        sex = "unknown"
        ctx.note("sexAtBirth", "defaulted" if not sex_raw else "standardized", 2.0, "blank sex" if not sex_raw else None)
    else:
        d = ctx.decide(
            "ambiguous_sex_code", sex_raw,
            f"Halcyon SEX code {sex_raw!r} has no direct Nimbus equivalent. Nimbus separates sex at birth (female/male/unknown) "
            "from gender identity. How should it map?",
            [{"key": "unknown_nonbinary", "label": "sexAtBirth=unknown, genderIdentity=non-binary"},
             {"key": "unknown_other", "label": "sexAtBirth=unknown, genderIdentity=other"},
             {"key": "unknown", "label": "sexAtBirth=unknown, genderIdentity not set"}],
            blocking=False, default="unknown", context={"code": sex_raw})
        sex = "unknown"
        gender = {"unknown_nonbinary": "non-binary", "unknown_other": "other"}.get(d["option"])
        ctx.note("sexAtBirth", "degraded" if d.get("defaulted") else "inferred", 2.0, f"Halcyon SEX={sex_raw}", sex_raw)

    race_txt = ctx.terms.norm(p["RACE"])
    race, eth = ctx.terms.race.get(race_txt, (None, None))
    races = [race] if race else (["unknown"] if not race_txt or (race_txt not in ctx.terms.race) else [])
    if race_txt and race_txt not in ctx.terms.race:
        ctx.note("race", "degraded", 0.5, f"race text {p['RACE']!r} not recognized", p["RACE"])
    elif not race_txt:
        ctx.note("race", "defaulted", 0.5)
    else:
        ctx.note("race", "standardized", 0.5)
    if race_txt == "hispanic":
        ctx.note("ethnicity", "inferred", 0.5, "'Hispanic' recorded in race field moved to ethnicity", p["RACE"])

    a08 = s.get("a08", {}).get(p["PAT_ID"])
    addr_raw = a08["addr"] if a08 and a08.get("addr", "").strip("^") else p["ADDR"]
    address = []
    if addr_raw and addr_raw.strip("^ "):
        crammed = "^" not in addr_raw
        if crammed:
            ad = parse_crammed_address(addr_raw, set(ctx.store.xget(ctx.run_id, "meta", "cities", [])))
            ctx.note("address", "inferred" if ad else "degraded", 1.0,
                     "address fields parsed from a single line" if ad else "unparseable single-line address kept as one line", addr_raw)
            ad = ad or demo.Address([addr_raw.strip()], "", "", "")
        else:
            ad = demo.parse_address(addr_raw)
            ctx.note("address", "exact" if a08 else "transformed", 1.0, "newer address from ADT A08" if a08 else None)
        a = {"lines": ad.lines}
        if ad.city:
            a["city"] = ad.city
        if ad.state:
            a["state"] = ad.state
        if ad.postal_code:
            a["postalCode"] = ad.postal_code
        address.append(a)

    telecom = []
    phones = [("home", a08["phone"] if a08 and a08.get("phone") else p["PHONE_HOME"]), ("mobile", p["PHONE_CELL"])]
    for use, raw in phones:
        if not raw:
            continue
        e164, ext = demo.normalize_phone(raw), bool(re.search(r"(?i)(x|ext\.?)\s*\d+\s*$", raw))
        if e164:
            telecom.append({"system": "phone", "value": e164, "use": use})
            ctx.note(f"telecom.{use}", "degraded" if ext else "transformed", 0.5, "extension dropped" if ext else None, raw if ext else None)
        else:
            ctx.note(f"telecom.{use}", "dropped", 0.5, "phone not normalizable to E.164", raw)

    identifiers = [{"system": ctx.profile.MRN_SYSTEM.format(fac=m["FAC_ID"]), "value": m["MRN"]} for m in members]
    ctx.note("identifiers", "exact", 2.0)
    for m in members:
        if m is not p:
            why = s["links"].get(m["PAT_ID"]) or "user-confirmed"
            ctx.note(f"identity.{m['PAT_ID']}", "inferred" if why != "adt_a40" else "exact", 0.5, f"chart linked ({why})")

    flags = {m["NKA_FLAG"].strip().upper() for m in members}
    nka = "Y" in flags and not s["has_allergy_rows"]
    if "Y" in flags and s["has_allergy_rows"]:
        ctx.decide(
            "nka_conflict", ctx.key,
            f"Patient {name.family}, {' '.join(name.given)} ({ctx.key}) is flagged 'no known allergies' in Halcyon but also has allergy "
            "entries. Bridge loaded the allergies and did NOT set the no-known-allergies flag. Please confirm.",
            [{"key": "keep_allergies", "label": "Correct: keep the allergy entries"},
             {"key": "review", "label": "Flag chart for clinical allergy reconciliation after go-live"}],
            blocking=False, default="keep_allergies", context={"members": [m["PAT_ID"] for m in members]})
        ctx.note("noKnownAllergies", "inferred", 2.0, "NKA flag conflicts with allergy rows; allergies kept", "Y")
    else:
        ctx.note("noKnownAllergies", "transformed", 1.0)

    other_names = []
    for al in s.get("aliases", []):
        n = demo.parse_name(fix_mojibake(al["ALIAS_NAME"])[0])
        other_names.append({"family": n.family, "given": n.given, "use": al["ALIAS_TYPE"].lower() or "old"})
    out: dict[str, Any] = {
        "identifiers": identifiers, "name": {"family": name.family, "given": name.given, "suffix": name.suffix},
        "birthDate": dob.value.isoformat(), "sexAtBirth": sex, "race": races, "address": address,
        "telecom": telecom, "noKnownAllergies": nka, "otherNames": other_names,
    }
    if gender:
        out["genderIdentity"] = gender
    if eth:
        out["ethnicity"] = eth
    deceased = parse_date8(p["DECEASED_DT"])
    if deceased:
        out["deceasedDate"] = deceased.isoformat()
    ctx.note("ssn4", "dropped", 0.2, "SSN fragment used for matching only; not stored in Nimbus")
    return out


def identity_summary(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p.get(k) for k in ("PAT_ID", "MRN", "FAC_ID", "PAT_NAME", "DOB", "SEX")}


# ----------------------------------------------------------------------------- coverage
REL_MAP = {"18": "self", "01": "spouse", "19": "child", "G8": "other"}


@mapper("Coverage")
def map_coverage(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    plan = ctx.require("Plan", s["PLAN_ID"])
    plan_payer = ctx.store.record(ctx.run_id, "Plan", s["PLAN_ID"])
    payer = ctx.require("Payer", plan_payer["source"]["PAYER_ID"]) if plan_payer else None
    rel = REL_MAP.get(s["REL_CODE"].strip())
    if rel:
        ctx.note("subscriberRelationship", "standardized", 1.0)
    else:
        as_of = date.fromisoformat(ctx.store.run(ctx.run_id)["config"]["as_of"])
        dob = demo.parse_legacy_date(s["_PAT_DOB"], as_of).value
        guess = "child" if dob and (as_of - dob).days < 18 * 365 else "self"
        d = ctx.decide(
            "missing_subscriber_relationship", "blank",
            "Some Halcyon coverages have no subscriber relationship code. Nimbus requires one. Bridge defaults to 'self' for "
            "adults and 'child' for minors. Accept, or send them to registration for review?",
            [{"key": "age_rule", "label": "Accept the age-based default"},
             {"key": "other", "label": "Use 'other' for all of them and flag for registration"}],
            blocking=False, default="age_rule")
        rel = guess if d["option"] == "age_rule" else "other"
        ctx.note("subscriberRelationship", "inferred", 1.0, f"relationship missing; set to {rel}", s["REL_CODE"])
    order = int(s["COB_ORDER"] or 1)
    dup_key = f"cob:{s['PAT_ID']}:{order}"
    owner = ctx.store.xget(ctx.run_id, "cob", dup_key)
    if owner and owner != ctx.key:
        order += 1
        ctx.note("order", "inferred", 1.0, f"duplicate COB order {order - 1} (also on {owner}); moved to {order}", s["COB_ORDER"])
    else:
        ctx.store.xset(ctx.run_id, "cob", dup_key, ctx.key)
        ctx.note("order", "exact", 1.0)
    out: dict[str, Any] = {"patient": patient, "payer": payer, "plan": plan, "memberId": s["MEMBER_ID"],
                           "subscriberRelationship": rel, "order": order}
    eff = parse_local(s["EFF_DT"])
    tz = _tz(ctx, s["_PAT_FAC"]) if eff else None
    if eff and tz:
        out["period"] = {"start": localize(eff, tz)[0].isoformat()}
        term = parse_local(s["TERM_DT"])
        if term:
            out["period"]["end"] = localize(term, tz)[0].isoformat()
        ctx.note("period", "transformed", 0.5)
    ctx.note("memberId", "exact", 1.0)
    return out


# ----------------------------------------------------------------------------- encounter
STATUS_MAP = {"C": "finished", "X": "cancelled", "A": "in-progress"}


@mapper("Encounter")
def map_encounter(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    vt = s["VISIT_TYPE"].strip()
    cls = ctx.terms.visit_class.get(vt)
    if cls:
        ctx.note("class", "standardized", 1.0)
    else:
        d = ctx.decide(
            "unknown_visit_type", vt or "(blank)",
            f"Halcyon visit type {vt!r} is not in the visit-type crosswalk. Which Nimbus encounter class should it become?",
            [{"key": c, "label": c} for c in ("ambulatory", "emergency", "inpatient", "observation", "virtual")]
            + [{"key": "skip", "label": "Do not convert these visits"}],
            blocking=True, context={"visit_type": vt, "example": {k: s[k] for k in ("VISIT_ID", "DEPT_ID", "REASON_TEXT")}})
        if d is None:
            return None
        if d["option"] == "skip":
            ctx.note("record", "dropped", 1.0, f"visit type {vt} excluded by user")
            return None
        cls = d["option"]
        ctx.note("class", "inferred", 1.0, f"visit type {vt} mapped by user rule", vt)
    status = STATUS_MAP.get(s["STATUS"].strip(), "finished")
    ctx.note("status", "standardized" if s["STATUS"].strip() in STATUS_MAP else "defaulted", 0.5)
    fac = s["_DEPT_FAC"] or s["_PAT_FAC"]
    start = _zoned(ctx, s["ADMIT_DT"], fac, "period.start", 1.0)
    if start is None:
        ctx.note("record", "dropped", 1.0, "no usable admit time", s["ADMIT_DT"])
        return None
    period: dict[str, Any] = {"start": start.isoformat()}
    end = _zoned(ctx, s["DISCH_DT"], fac, "period.end", 0.5) if s["DISCH_DT"] else None
    if end:
        period["end"] = end.isoformat()
    elif cls == "inpatient" and status == "finished":
        d = ctx.decide(
            "missing_discharge", "inpatient",
            "Some completed Halcyon inpatient stays have no discharge time; Nimbus requires one for finished inpatient encounters. "
            "How should Bridge proceed?",
            [{"key": "unknown_end", "label": "Load as status in-progress (discharge unknown) and flag for HIM review"},
             {"key": "admit_plus_1d", "label": "Estimate discharge as admit + 24h (marked inferred)"},
             {"key": "skip", "label": "Do not convert these stays"}],
            blocking=True)
        if d is None:
            return None
        if d["option"] == "skip":
            ctx.note("record", "dropped", 1.0, "inpatient stay without discharge excluded by user")
            return None
        if d["option"] == "admit_plus_1d":
            from datetime import timedelta
            period["end"] = (start + timedelta(hours=24)).isoformat()
            ctx.note("period.end", "inferred", 1.0, "discharge estimated as admit+24h")
        else:
            status = "in-progress"
            ctx.note("status", "degraded", 1.0, "discharge missing; loaded as in-progress")
    out: dict[str, Any] = {"patient": patient, "class": cls, "status": status, "period": period}
    loc = ctx.optional("Location", location_key(ctx, s["DEPT_ID"], s["_DEPT_FAC"], s["_PAT_FAC"]), "location")
    if loc:
        out["location"] = loc
        ctx.note("location", "inferred" if not s["_DEPT_FAC"] else "exact", 0.5)
    prov = ctx.optional("Practitioner", s["ATTEND_PROV_ID"], "practitioners")
    if prov:
        out["practitioners"] = [prov]
        ctx.note("practitioners", "exact", 0.5)
    if s["REASON_TEXT"]:
        out["reason"] = {"text": s["REASON_TEXT"]}
        ctx.note("reason", "exact", 0.3)
    return out


# ----------------------------------------------------------------------------- condition
CLIN_STATUS = {"A": "active", "I": "inactive", "R": "resolved"}


@mapper("Condition")
def map_condition(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    patient = ctx.patient(s["PAT_ID"])
    code, ctype, desc = s["CODE"].strip(), s["CODE_TYPE"].strip(), s["DX_DESC"].strip()
    if code and not ctype:
        ctype = "10" if ICD10_RE.match(code) else "9" if ICD9_RE.match(code) else "L"
        ctx.note("code.system", "inferred", 1.0, f"code type blank; inferred ICD-{ctype}" if ctype != "L" else "code type blank", s["CODE_TYPE"])
    icd10: str | None = None
    if not code:
        icd10 = None
    elif ctype == "10":
        if code in ctx.terms.icd10_retired:
            icd10 = _choose(ctx, "retired_icd10", code, ctx.terms.icd10_retired[code], desc,
                            f"ICD-10 code {code} ({desc}) was retired and has more than one replacement.")
            if icd10 is None and ctx.held_by:
                return None
        elif ICD10_RE.match(code):
            icd10 = code
            ctx.note("code", "exact", 3.0)
        else:
            ctx.note("code", "degraded", 3.0, f"invalid ICD-10 code {code!r}", code)
    elif ctype == "9":
        cands = [c for c, _ in ctx.terms.icd9.get(code, [])]
        if not cands:
            icd10 = _choose(ctx, "unmapped_icd9", code, [], desc, f"ICD-9 code {code} ({desc}) is not in the ICD-9 to ICD-10 crosswalk.")
        elif len(cands) == 1:
            icd10 = cands[0]
            ctx.note("code", "standardized", 3.0, f"ICD-9 {code} -> {icd10}", code)
        else:
            icd10 = _choose(ctx, "icd9_one_to_many", code, cands, desc,
                            f"ICD-9 code {code} ({desc}) maps to several ICD-10 codes. Which should Bridge use?")
        if icd10 is None and ctx.held_by:
            return None
    else:  # local
        hit = ctx.terms.local_dx.get(code)
        if hit:
            icd10 = hit[0]
            ctx.note("code", "standardized", 3.0, f"local {code} -> {icd10}", code)
        else:
            icd10 = _choose(ctx, "unmapped_local_dx", code, [], desc, f"Halcyon local problem code {code} ({desc}) has no crosswalk entry.")
            if icd10 is None and ctx.held_by:
                return None

    status_raw = s["STATUS"].strip()
    status = CLIN_STATUS.get(status_raw, "active")
    ctx.note("clinicalStatus", "standardized" if status_raw in CLIN_STATUS else "defaulted", 1.0,
             None if status_raw in CLIN_STATUS else "blank status loaded as active")
    pkey = ctx.patient_key(s["PAT_ID"])
    if ctx.dedupe(pkey or s["PAT_ID"], icd10 or ctx.terms.norm(desc)):
        return None
    out: dict[str, Any] = {"patient": patient, "clinicalStatus": status}
    if icd10:
        out["code"] = {"coding": [{"system": "ICD-10-CM", "code": icd10}], "text": desc.capitalize() or None}
        out["verificationStatus"] = "confirmed"
    else:
        out["code"] = {"text": desc or code}
        out["verificationStatus"] = "unconfirmed"
        if not code:
            ctx.decide("free_text_problem", ctx.terms.norm(desc),
                       f"Problem-list entry '{desc}' is free text only. Bridge loaded it as an unconfirmed, uncoded problem. "
                       "Provide an ICD-10 code to code it, or keep as text.",
                       [{"key": "keep_text", "label": "Keep as uncoded text"},
                        {"key": "code", "label": "Code it as ICD-10 (enter code)", "needs_value": True}],
                       blocking=False, default="keep_text")
            rule = ctx.store.rule(ctx.run_id, "free_text_problem", ctx.terms.norm(desc))
            if rule and rule.get("option") == "code" and rule.get("value") and ICD10_RE.match(rule["value"]):
                out["code"] = {"coding": [{"system": "ICD-10-CM", "code": rule["value"]}], "text": desc}
                out["verificationStatus"] = "confirmed"
                ctx.note("code", "inferred", 3.0, "coded by user from free text", desc)
            else:
                ctx.note("code", "degraded", 3.0, "free-text problem loaded uncoded", desc)
    onset = parse_date8(s["ONSET_DT"])
    if onset:
        out["onsetDate"] = onset.isoformat()
        ctx.note("onsetDate", "transformed", 0.5)
    resolved = parse_date8(s["RESOLVED_DT"])
    if resolved:
        out["abatementDate"] = resolved.isoformat()
    if s["VISIT_ID"]:
        enc = ctx.optional("Encounter", s["VISIT_ID"], "encounter")
        if enc:
            out["encounter"] = enc
    return out


def _choose(ctx: MapContext, kind: str, code: str, cands: list[str], desc: str, prompt: str) -> str | None:
    opts = [{"key": c, "label": f"Use ICD-10 {c}"} for c in cands]
    opts += [{"key": "other", "label": "Use a different ICD-10 code (enter it)", "needs_value": True},
             {"key": "text", "label": "Load as uncoded, unconfirmed text"}]
    d = ctx.decide(kind, code, prompt, opts, blocking=True, context={"code": code, "description": desc, "candidates": cands})
    if d is None:
        return None
    if d["option"] == "text":
        ctx.note("code", "degraded", 3.0, f"{code} loaded as text per user rule", code)
        return None
    chosen = d.get("value") if d["option"] == "other" else d["option"]
    if not chosen or not ICD10_RE.match(chosen):
        ctx.note("code", "degraded", 3.0, f"rule for {code} gave no valid ICD-10; loaded as text", code)
        return None
    ctx.note("code", "inferred", 3.0, f"{code} -> {chosen} per user rule", code)
    return chosen


# ----------------------------------------------------------------------------- allergy
CRITICALITY = {"SEV": "high", "MOD": "low", "MILD": "low"}
REACTION_SEVERITY = {"SEV": "severe", "MOD": "moderate", "MILD": "mild"}


@mapper("AllergyIntolerance")
def map_allergy(ctx: MapContext) -> dict[str, Any] | None:
    s = ctx.src
    allergen = s["ALLERGEN"].strip()
    if allergen.upper() in ("NKA", "NKDA"):
        ctx.note("record", "dropped", 1.0, "'no known allergies' row folded into Patient.noKnownAllergies", allergen)
        return None
    patient = ctx.patient(s["PAT_ID"])
    hit = ctx.terms.allergens.get(ctx.terms.norm(allergen))
    if hit:
        system, code, display = hit
        substance = {"coding": [{"system": system, "code": code, "display": display}], "text": allergen}
        coding_status = "coded"
        ctx.note("substance", "standardized", 3.0)
    else:
        substance = {"text": allergen}
        coding_status = "uncoded"
        ctx.note("substance", "degraded", 3.0, "allergen not in crosswalk; loaded as uncoded text", allergen)
    pkey = ctx.patient_key(s["PAT_ID"])
    if ctx.dedupe(pkey or s["PAT_ID"], f"{hit[0]}|{hit[1]}" if hit else ctx.terms.norm(allergen)):
        return None
    sev = s["SEVERITY"].strip().upper()
    reactions = []
    for part in [p.strip() for p in s["REACTION"].split(";") if p.strip()]:
        r = ctx.terms.reactions.get(ctx.terms.norm(part))
        if part.lower() == "unknown":
            ctx.note("reactions", "dropped", 0.5, "reaction recorded as 'unknown'", part)
            continue
        man = {"coding": [{"system": "SNOMED-CT", "code": r[0], "display": r[1]}], "text": part} if r else {"text": part}
        reactions.append({"manifestation": man, **({"severity": REACTION_SEVERITY[sev]} if sev in REACTION_SEVERITY else {})})
        ctx.note(f"reactions.{part}", "standardized" if r else "degraded", 0.5)
    crit = CRITICALITY.get(sev, "unable-to-assess")
    ctx.note("criticality", "inferred" if sev else "defaulted", 1.0,
             f"Halcyon reaction severity {sev or '(blank)'} used to derive criticality", sev or None)
    out: dict[str, Any] = {"patient": patient, "substance": substance, "codingStatus": coding_status,
                           "reactions": reactions, "criticality": crit}
    rec = parse_date8(s["ENTERED_DT"])
    if rec:
        out["recordedDate"] = rec.isoformat()
    return out
