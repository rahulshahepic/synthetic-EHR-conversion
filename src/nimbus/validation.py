"""Semantic validation for Nimbus resources. Every problem gets a stable issue code."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator

from pydantic import BaseModel, ValidationError

from . import models as m
from .valuesets import VALUESETS


@dataclass
class Issue:
    code: str
    message: str
    field: str | None = None
    severity: str = "error"  # error | warning

    def to_dict(self) -> dict[str, Any]:
        # Same as dataclasses.asdict(self) (all fields are str/None), without its recursive deep copy.
        return {"code": self.code, "message": self.message, "field": self.field, "severity": self.severity}


CODE_PATTERNS = {
    "ICD-10-CM": re.compile(r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-Z]{1,4})?$"),
    "SNOMED-CT": re.compile(r"^[1-9][0-9]{5,17}$"),
    "LOINC": re.compile(r"^[0-9]{1,5}-[0-9]$"),
    "RxNorm": re.compile(r"^[0-9]{2,8}$"),
    "CVX": re.compile(r"^[0-9]{1,3}$"),
    "CPT": re.compile(r"^([0-9]{5}|[0-9]{4}[FTU])$"),
    "HCPCS": re.compile(r"^[A-V][0-9]{4}$"),
}

UCUM_UNITS = {
    "mg/dL", "mmol/L", "meq/L", "g/dL", "g/L", "%", "10*3/uL", "10*6/uL", "U/L", "ng/mL",
    "pg/mL", "mIU/L", "uIU/mL", "fL", "pg", "mL/min/{1.73_m2}", "mm[Hg]", "Cel", "[degF]",
    "kg", "g", "[lb_av]", "cm", "[in_i]", "/min", "kg/m2", "s", "{ratio}", "{INR}", "mg",
    "ug", "mL", "L", "[iU]", "{tab}", "{cap}", "{puff}", "{drop}", "{patch}", "{spray}",
    "mg/L", "ug/dL", "ng/dL", "umol/L", "mm/h", "1", "mg/mL", "[iU]/mL", "mL/h", "10*9/L", "nmol/L",
}

# Physiologic plausibility for vital signs: loinc -> {unit: (low, high)}
VITAL_LIMITS: dict[str, dict[str, tuple[float, float]]] = {
    "29463-7": {"kg": (0.2, 700), "[lb_av]": (0.5, 1500), "g": (200, 700_000)},   # body weight
    "8302-2": {"cm": (20, 275), "[in_i]": (8, 108)},                               # body height
    "8310-5": {"Cel": (25, 45), "[degF]": (77, 113)},                              # body temp
    "8867-4": {"/min": (10, 300)},                                                 # heart rate
    "9279-1": {"/min": (2, 80)},                                                   # resp rate
    "59408-5": {"%": (40, 100)},                                                   # SpO2
    "39156-5": {"kg/m2": (5, 150)},                                                # BMI
    "8480-6": {"mm[Hg]": (40, 300)},                                               # systolic
    "8462-4": {"mm[Hg]": (20, 200)},                                               # diastolic
}
BP_PANEL = "85354-9"

GENERIC_USERNAME = re.compile(
    r"^(FRONTDESK|FRONT_DESK|NURSE|NURSING|TEMP|ADMIN|REGISTRATION|REG|LAB|SCHED|"
    r"SCHEDULING|BILLING|TRIAGE|GUEST|TEST|SHARED)[_-]?\d*$",
    re.IGNORECASE,
)

# (resource type, field path) -> referenced resource type. "[]" marks a list.
REF_FIELDS: dict[str, dict[str, str]] = {
    "Organization": {"partOf": "Organization"},
    "Location": {"department": "Organization"},
    "Plan": {"payer": "Payer"},
    "Coverage": {"patient": "Patient", "payer": "Payer", "plan": "Plan"},
    "Encounter": {"patient": "Patient", "location": "Location", "practitioners[]": "Practitioner"},
    "Condition": {"patient": "Patient", "encounter": "Encounter"},
    "AllergyIntolerance": {"patient": "Patient"},
    "MedicationRequest": {"patient": "Patient", "encounter": "Encounter", "prescriber": "Practitioner"},
    "Observation": {"patient": "Patient", "encounter": "Encounter"},
    "Immunization": {"patient": "Patient", "performer": "Practitioner"},
    "DocumentReference": {"patient": "Patient", "encounter": "Encounter", "author": "Practitioner"},
    "Appointment": {"patient": "Patient", "practitioner": "Practitioner", "location": "Location"},
    "ChargeItem": {"patient": "Patient", "encounter": "Encounter"},
    "UserAccount": {"practitioner": "Practitioner"},
}


def iter_refs(resource_type: str, model: BaseModel) -> Iterator[tuple[str, m.Ref, str]]:
    """Yield (field, Ref, expected_type) for every reference in a resource."""
    for field, target in REF_FIELDS.get(resource_type, {}).items():
        if field.endswith("[]"):
            name = field[:-2]
            for i, ref in enumerate(getattr(model, name) or []):
                yield f"{name}[{i}]", ref, target
        else:
            ref = getattr(model, field, None)
            if ref is not None:
                yield field, ref, target


def npi_is_valid(npi: str) -> bool:
    if not re.fullmatch(r"[0-9]{10}", npi):
        return False
    digits = [int(c) for c in "80840" + npi[:9]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(npi[9])


def parse(resource_type: str, payload: dict[str, Any]) -> tuple[BaseModel | None, list[Issue]]:
    cls = m.RESOURCE_MODELS.get(resource_type)
    if cls is None:
        return None, [Issue("E_RESOURCE_TYPE", f"unknown resource type {resource_type!r}")]
    try:
        model = cls.model_validate(payload)
    except ValidationError as exc:
        issues = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            code = {"missing": "E_REQUIRED", "extra_forbidden": "E_UNKNOWN_FIELD"}.get(err["type"], "E_TYPE")
            issues.append(Issue(code, err["msg"], loc))
        return None, issues
    return model, semantic_issues(resource_type, model)


def _in(vs: str, value: str | None, field: str, issues: list[Issue]) -> None:
    if value is not None and value not in VALUESETS[vs]:
        issues.append(Issue("E_VALUESET", f"{value!r} not in valueset {vs}", field))


def _coding_systems(cc: m.CodeableConcept, allowed: set[str], field: str, issues: list[Issue], required: bool = True) -> None:
    if required and not cc.coding:
        issues.append(Issue("E_CODE_SYSTEM", f"coding from {sorted(allowed)} required", field))
    for i, c in enumerate(cc.coding):
        if c.system not in allowed:
            issues.append(Issue("E_CODE_SYSTEM", f"system {c.system!r} not allowed; use {sorted(allowed)}", f"{field}.coding[{i}]"))
        elif not CODE_PATTERNS[c.system].match(c.code):
            issues.append(Issue("E_CODE_FORMAT", f"{c.code!r} is not a valid {c.system} code", f"{field}.coding[{i}]"))


def _quantity(q: m.Quantity, field: str, issues: list[Issue]) -> None:
    if q.unit not in UCUM_UNITS:
        issues.append(Issue("E_UNIT", f"unit {q.unit!r} is not an accepted UCUM unit", f"{field}.unit"))
    _in("comparator", q.comparator, f"{field}.comparator", issues)


def _vital_limit(code: str, q: m.Quantity, field: str, issues: list[Issue]) -> None:
    limits = VITAL_LIMITS.get(code)
    if not limits:
        return
    rng = limits.get(q.unit)
    if rng is None:
        issues.append(Issue("E_UNIT", f"unit {q.unit!r} not valid for vital {code}", f"{field}.unit"))
    elif not rng[0] <= q.value <= rng[1]:
        issues.append(Issue("E_PLAUSIBILITY", f"{q.value} {q.unit} outside plausible range {rng}", f"{field}.value"))


def semantic_issues(rt: str, r: BaseModel) -> list[Issue]:
    issues: list[Issue] = []
    today = date.today()

    if isinstance(r, m.Organization):
        _in("organization-type", r.type, "type", issues)
        if r.type != "system" and r.partOf is None:
            issues.append(Issue("E_REQUIRED", "partOf required for site/department", "partOf"))
    elif isinstance(r, m.Practitioner):
        _in("specialty", r.specialty, "specialty", issues)
        if r.npi is not None and not npi_is_valid(r.npi):
            issues.append(Issue("E_NPI", f"NPI {r.npi!r} fails check digit", "npi"))
        if r.billing and r.npi is None:
            issues.append(Issue("E_REQUIRED", "NPI required for billing practitioners", "npi"))
    elif isinstance(r, m.Patient):
        if not r.identifiers:
            issues.append(Issue("E_REQUIRED", "at least one identifier required", "identifiers"))
        if not r.name.family.strip():
            issues.append(Issue("E_REQUIRED", "family name required", "name.family"))
        if r.birthDate > today or r.birthDate.year < 1890:
            issues.append(Issue("E_PLAUSIBILITY", f"birthDate {r.birthDate} implausible", "birthDate"))
        if r.deceasedDate and r.deceasedDate < r.birthDate:
            issues.append(Issue("E_PLAUSIBILITY", "deceasedDate before birthDate", "deceasedDate"))
        _in("sex-at-birth", r.sexAtBirth, "sexAtBirth", issues)
        _in("gender-identity", r.genderIdentity, "genderIdentity", issues)
        for i, race in enumerate(r.race):
            _in("race", race, f"race[{i}]", issues)
        _in("ethnicity", r.ethnicity, "ethnicity", issues)
        for i, t in enumerate(r.telecom):
            _in("telecom-system", t.system, f"telecom[{i}].system", issues)
            if t.system == "phone" and not re.fullmatch(r"\+1[2-9][0-9]{9}", t.value):
                issues.append(Issue("E_FORMAT", f"phone {t.value!r} not E.164 (+1NXXNXXXXXX)", f"telecom[{i}].value"))
        for i, a in enumerate(r.address):
            if a.state and not re.fullmatch(r"[A-Z]{2}", a.state):
                issues.append(Issue("E_FORMAT", "state must be 2-letter code", f"address[{i}].state"))
            if a.postalCode and not re.fullmatch(r"[0-9]{5}(-[0-9]{4})?", a.postalCode):
                issues.append(Issue("E_FORMAT", "postalCode must be ZIP or ZIP+4", f"address[{i}].postalCode"))
    elif isinstance(r, m.Coverage):
        _in("subscriber-relationship", r.subscriberRelationship, "subscriberRelationship", issues)
        if r.order < 1:
            issues.append(Issue("E_TYPE", "order must be >= 1", "order"))
    elif isinstance(r, m.Encounter):
        _in("encounter-class", r.encounterClass, "class", issues)
        _in("encounter-status", r.status, "status", issues)
        if r.period.start.tzinfo is None:
            issues.append(Issue("E_TIMEZONE", "period.start must include a UTC offset", "period.start"))
        if r.period.end is not None:
            if r.period.end.tzinfo is None:
                issues.append(Issue("E_TIMEZONE", "period.end must include a UTC offset", "period.end"))
            elif r.period.start.tzinfo is not None and r.period.end < r.period.start:
                issues.append(Issue("E_PLAUSIBILITY", "period.end before period.start", "period.end"))
        if r.encounterClass == "inpatient" and r.status == "finished" and r.period.end is None:
            issues.append(Issue("E_REQUIRED", "finished inpatient encounters require period.end", "period.end"))
    elif isinstance(r, m.Condition):
        _in("condition-clinical-status", r.clinicalStatus, "clinicalStatus", issues)
        _in("condition-verification-status", r.verificationStatus, "verificationStatus", issues)
        if r.code.coding:
            _coding_systems(r.code, {"ICD-10-CM", "SNOMED-CT"}, "code", issues)
        elif not (r.code.text and r.verificationStatus == "unconfirmed"):
            issues.append(Issue("E_CODE_SYSTEM", "uncoded conditions must have code.text and verificationStatus=unconfirmed", "code"))
    elif isinstance(r, m.AllergyIntolerance):
        _in("allergy-coding-status", r.codingStatus, "codingStatus", issues)
        _in("allergy-criticality", r.criticality, "criticality", issues)
        if r.codingStatus == "coded":
            _coding_systems(r.substance, {"RxNorm", "SNOMED-CT"}, "substance", issues)
        elif r.substance.coding or not r.substance.text:
            issues.append(Issue("E_CODE_SYSTEM", "uncoded substance must have text and no coding", "substance"))
        for i, rx in enumerate(r.reactions):
            if rx.manifestation.coding:
                _coding_systems(rx.manifestation, {"SNOMED-CT"}, f"reactions[{i}].manifestation", issues)
            elif not rx.manifestation.text:
                issues.append(Issue("E_REQUIRED", "reaction needs coding or text", f"reactions[{i}].manifestation"))
    elif isinstance(r, m.MedicationRequest):
        _coding_systems(r.medication, {"RxNorm"}, "medication", issues)
        _in("medication-status", r.status, "status", issues)
        d = r.dosage
        _in("route", d.route, "dosage.route", issues)
        if d.frequency:
            _in("period-unit", d.frequency.periodUnit, "dosage.frequency.periodUnit", issues)
        if d.doseQuantity:
            _quantity(d.doseQuantity, "dosage.doseQuantity", issues)
        if r.dosageStructured:
            missing = [f for f in ("doseQuantity", "route") if getattr(d, f) is None]
            if d.frequency is None and not d.asNeeded:
                missing.append("frequency")
            for f in missing:
                issues.append(Issue("E_REQUIRED", f"structured dosage requires {f}", f"dosage.{f}"))
        elif not d.text:
            issues.append(Issue("E_REQUIRED", "dosage.text required when dosageStructured=false", "dosage.text"))
    elif isinstance(r, m.Observation):
        _in("observation-category", r.category, "category", issues)
        _in("observation-status", r.status, "status", issues)
        _in("interpretation", r.interpretation, "interpretation", issues)
        _coding_systems(r.code, {"LOINC"}, "code", issues)
        if r.effective.tzinfo is None:
            issues.append(Issue("E_TIMEZONE", "effective must include a UTC offset", "effective"))
        values = [v for v in (r.valueQuantity, r.valueCodeable, r.valueString) if v is not None]
        loinc = r.code.coding[0].code if r.code.coding else ""
        if r.components:
            if values:
                issues.append(Issue("E_VALUE", "panel observations carry values in components only", "valueQuantity"))
            for i, comp in enumerate(r.components):
                _coding_systems(comp.code, {"LOINC"}, f"components[{i}].code", issues)
                _quantity(comp.valueQuantity, f"components[{i}].valueQuantity", issues)
                if comp.code.coding:
                    _vital_limit(comp.code.coding[0].code, comp.valueQuantity, f"components[{i}].valueQuantity", issues)
        elif len(values) != 1:
            issues.append(Issue("E_VALUE", "exactly one of valueQuantity/valueCodeable/valueString required", "value"))
        if loinc == BP_PANEL and len(r.components) != 2:
            issues.append(Issue("E_VALUE", "blood pressure requires systolic and diastolic components", "components"))
        if r.valueQuantity:
            _quantity(r.valueQuantity, "valueQuantity", issues)
            if r.category == "vital-signs":
                _vital_limit(loinc, r.valueQuantity, "valueQuantity", issues)
        _in("coded-result", r.valueCodeable, "valueCodeable", issues)
    elif isinstance(r, m.Immunization):
        _coding_systems(r.vaccine, {"CVX"}, "vaccine", issues)
        if r.occurrenceDate > today:
            issues.append(Issue("E_PLAUSIBILITY", "occurrenceDate in the future", "occurrenceDate"))
    elif isinstance(r, m.DocumentReference):
        _coding_systems(r.type, {"LOINC"}, "type", issues)
        if r.contentType not in ("text/plain", "text/markdown"):
            issues.append(Issue("E_FORMAT", "contentType must be text/plain or text/markdown", "contentType"))
        if r.content.lstrip().startswith("{\\rtf") or "\\par" in r.content:
            issues.append(Issue("E_FORMAT", "RTF content is not accepted", "content"))
        if len(r.content.encode("utf-8")) > 1_000_000:
            issues.append(Issue("E_SIZE", "content exceeds 1 MB", "content"))
    elif isinstance(r, m.Appointment):
        _in("appointment-status", r.status, "status", issues)
        if r.start.tzinfo is None or r.end.tzinfo is None:
            issues.append(Issue("E_TIMEZONE", "start/end must include a UTC offset", "start"))
        elif r.end <= r.start:
            issues.append(Issue("E_PLAUSIBILITY", "end must be after start", "end"))
    elif isinstance(r, m.ChargeItem):
        _coding_systems(r.code, {"CPT", "HCPCS"}, "code", issues)
        if len(r.modifiers) > 4:
            issues.append(Issue("E_VALUE", "at most 4 modifiers", "modifiers"))
        for i, mod in enumerate(r.modifiers):
            if not re.fullmatch(r"[0-9A-Z]{2}", mod):
                issues.append(Issue("E_FORMAT", f"modifier {mod!r} must be 2 alphanumerics", f"modifiers[{i}]"))
        if r.amount < 0:
            issues.append(Issue("E_VALUE", "amount must be >= 0", "amount"))
        if r.units < 1:
            issues.append(Issue("E_VALUE", "units must be >= 1", "units"))
    elif isinstance(r, m.UserAccount):
        if GENERIC_USERNAME.match(r.username):
            issues.append(Issue("E_GENERIC_ACCOUNT", f"shared/generic account {r.username!r} not allowed", "username"))

    return issues
