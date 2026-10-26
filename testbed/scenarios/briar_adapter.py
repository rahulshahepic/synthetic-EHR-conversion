"""Explicitly authored source adapter, consuming the discovered Briar spec.

This fills the current builder's missing source-to-domain mapping step. It is
not generated code. All reads use the generated binding; no fixture truth or
generator knowledge is imported. Existing default mappers are restored after
the scenario ends.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from bridge.extract.registry import register_reader
from bridge.interview.reader import FixedWidthExport, make_factory, stage_records
from bridge.mapping.base import MAPPERS

TYPES = ["Patient", "Encounter", "Condition", "AllergyIntolerance", "MedicationRequest", "Observation", "DocumentReference", "Appointment", "ChargeItem"]


def fact(spec, subject, predicate):
    matches = [r["value"] for r in spec["rules"] if r["subject"] == subject and r["predicate"] == predicate]
    if len(matches) != 1:
        raise ValueError(f"missing or ambiguous discovery rule: {subject}/{predicate}")
    return matches[0]


def local_time(day, clock, tz):
    naive = datetime.strptime(day, "%Y%m%d")
    if clock == "2400":
        naive += timedelta(days=1)
    else:
        if not re.fullmatch(r"\d{4}", clock) or int(clock[:2]) > 23 or int(clock[2:]) > 59:
            raise ValueError("invalid local time")
        naive = naive.replace(hour=int(clock[:2]), minute=int(clock[2:]))
    zone = ZoneInfo(tz)
    candidates = {naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                  for fold in (0, 1)
                  if naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive}
    if len(candidates) != 1:
        raise ValueError("DST wall-clock time ambiguous or nonexistent")
    # Nimbus serializes UTC as Z. Bridge's current read-back checker compares
    # strings literally, so use the target's canonical representation.
    return next(iter(candidates)).isoformat().replace("+00:00", "Z")


def install(root: Path):
    spec = json.loads((root / "spec/spec.json").read_text())
    binding = spec["reader_binding"]
    # Fail closed if this adapter was not authored for the emitted semantics.
    assert fact(spec, "identity", "keying_story")["key_fields"] == ["REG.TXT.SITE+REG.TXT.CHART"]
    assert fact(spec, "field:LAB.TXT.UNIT", "convention") == "row_unit_overrides_dictionary"
    assert fact(spec, "semantics", "lab")["latest"] == "max_numeric_revision"
    assert fact(spec, "semantics", "lab")["deletion"] == "entire_site_accession"
    assert fact(spec, "semantics", "notes")["whitespace"] == "right_trim_only"
    assert fact(spec, "semantics", "notes")["order"] == "numeric_SEQ"
    assert fact(spec, "semantics", "allergy")["positive_overrides_NKA"] is True
    assert fact(spec, "field:REG.TXT.DOB", "convention") == {"format": "YYYYMMDD", "other": "runtime_question"}
    assert fact(spec, "semantics", "timezone")["ambiguous_or_nonexistent"] == "runtime_question"
    assert fact(spec, "semantics", "timezone")["2400"] == "next_midnight"
    assert fact(spec, "semantics", "lab")["missing_glucose_unit"] == "runtime_question"
    assert fact(spec, "field:LAB.TXT.RESULT", "convention")["comparator"] == "preserve"
    assert fact(spec, "field:BILL.TXT.AMOUNT", "convention")["negative"] == "runtime_question"
    profile = SimpleNamespace(READER="briar_scenario", MERGE_POLICY="route_to_reconciliation", SOURCE_SYSTEM="briar")
    mapping = {name: fact(spec, "codeset:" + name, "crosswalk") for name in ("lab", "medication", "diagnosis", "charge")}
    state = {"raw": [], "accounting": []}

    def native(source): return make_factory(binding)(source)
    register_reader("briar_native", native)

    def factory(source):
        exp = FixedWidthExport(source, binding)
        def stage(store, rid, exp, profile):
            if exp.manifest.get("version") != "3.7":
                raise ValueError("Briar adapter is approved only for delivery 3.7; re-interview changed versions")
            raw = stage_records(exp)
            state["raw"] = raw
            audit = []
            grouped = defaultdict(list)
            for row in raw:
                grouped[row["record_type"]].append(row)
            demographics = defaultdict(list)
            for r in grouped["REG"]:
                p = r["payload"]
                demographics[(p["SITE"], p["NAME"], p["DOB"])].append(p["SITE"] + "|" + p["CHART"])
            candidates = {key: keys for keys in demographics.values() if len(keys) > 1 for key in keys}
            deleted = {(r["payload"]["SITE"], r["payload"]["ID"]) for r in grouped["JRN"] if r["payload"]["TABLE"] == "LAB" and r["payload"]["ACTION"] == "D"}
            if any(r["payload"]["TABLE"] != "LAB" or r["payload"]["ACTION"] != "D" for r in grouped["JRN"]):
                raise ValueError("unimplemented journal operation; re-interview before staging")
            versions = defaultdict(list)
            notes = defaultdict(list)
            staged = defaultdict(list)
            def add(rtype, key, payload, row, disposition="mapped_source", sources=None):
                p = dict(payload)
                p["PAT_ID"] = p["SITE"] + "|" + p["CHART"]
                lineage = {"channel": "briar_fixed_width", "file": row["record_type"] + ".TXT", "line": row["line"],
                           "source_key": row["source_key"], "spec": "spec/spec.json", "source_segments": sources or []}
                staged[rtype].append((key, p, lineage))
                audit.append({"file": lineage["file"], "line": row["line"], "disposition": disposition, "target": rtype + "/" + key})
            for row in raw:
                p, table = row["payload"], row["record_type"]
                pkey = p.get("SITE", "") + "|" + p.get("CHART", "")
                key = p.get("SITE", "") + "|" + p.get("ID", "")
                if table == "REG":
                    add("Patient", pkey, {**p, "IDENTITY_CANDIDATES": candidates.get(pkey, [])}, row)
                    store.xset(rid, "pat", pkey, pkey)
                    if p["ALLERGY"]:
                        add("AllergyIntolerance", pkey, {**p, "ALLERGEN": p["ALLERGY"].split(":")[0]}, row, "derived_allergy")
                elif table == "VIS": add("Encounter", key, p, row)
                elif table == "LAB": versions[(p["SITE"], p["ID"], p["TEST"])].append(row)
                elif table == "NOTE": notes[key].append(row)
                elif table == "JRN":
                    audit.append({"file": "JRN.TXT", "line": row["line"], "disposition": "applied_accession_withdrawal", "accession": key})
                else:
                    rt = {"MED": "MedicationRequest", "DX": "Condition", "APPT": "Appointment", "BILL": "ChargeItem"}[table]
                    add(rt, key, {**p, **({"FORM_CODE": p["DRUG"]} if table == "MED" else {})}, row)
            for (site, ident, test), revs in versions.items():
                latest = max(revs, key=lambda r: int(r["payload"]["REV"]))
                if len({int(r["payload"]["REV"]) for r in revs}) != len(revs):
                    raise ValueError("duplicate logical revision")
                p = latest["payload"]
                flag = re.search(r"([HL])$", p["RESULT"])
                add("Observation", "|".join((site, ident, test)), {**p, "_withdrawn": (site, ident) in deleted, "kind": "lab", "ABN_FLAG": flag[1] if flag else ""}, latest)
                for old in revs:
                    if old is not latest: audit.append({"file": "LAB.TXT", "line": old["line"], "disposition": "superseded_revision_archived", "target": "Observation/" + "|".join((site, ident, test))})
            # Generic reader strips both sides of fields. For clinical note
            # content reconstruct from its binding span, preserving indentation.
            # The measured difference is reported as a native-reader limitation.
            raw_note_lines = (exp.path / "NOTE.TXT").read_bytes().decode("latin-1").splitlines()
            text_field = next(f for fs in binding["files"]["NOTE"]["layouts"].values() for f in fs if f["name"] == "TEXT")
            for key, parts in notes.items():
                parts.sort(key=lambda r: int(r["payload"]["SEQ"]))
                seqs = [int(r["payload"]["SEQ"]) for r in parts]
                if seqs != list(range(1, len(seqs) + 1)): raise ValueError("note segments missing or duplicated")
                def content(r):
                    line = raw_note_lines[r["line"] - 1]
                    return line[text_field["start"]:text_field["start"] + text_field["width"]].rstrip(" ")
                add("DocumentReference", key, {**parts[0]["payload"], "TEXT": "\n".join(content(r) for r in parts)}, parts[0], sources=[r["line"] for r in parts])
                for part in parts[1:]: audit.append({"file": "NOTE.TXT", "line": part["line"], "disposition": "assembled_continuation", "target": "DocumentReference/" + key})
            state["accounting"] = audit
            expected = {(r["record_type"] + ".TXT", r["line"]) for r in raw}
            accounted = {(r["file"], r["line"]) for r in audit}
            if expected != accounted: raise ValueError("unaccounted physical source rows")
            return {rt: store.stage(rid, rt, vals) for rt, vals in staged.items()}
        return exp, stage
    register_reader(profile.READER, factory)

    def hold(ctx, kind, key, prompt):
        kind = "briar_" + kind
        options = [{"key": "defer", "label": "Keep quarantined; additional source evidence is required"}]
        context = {"source": ctx.src, "synthetic": True}
        ctx.decide(kind, key, prompt, options, blocking=True, context=context)
        # Acknowledging that review is needed does not supply a clinical value.
        # Even a previously answered deferral must keep the record held. A new
        # verified source value/spec rule, not 'defer', is how it can be released.
        if ctx.held_by is None:
            q = ctx.store.upsert_question(ctx.run_id, kind, key, prompt, options, True, context, None)
            ctx.held_by = q["id"]
            ctx.store.link_question(q["id"], ctx.rtype, ctx.key, used_default=False)
        return None
    def patient(ctx): return ctx.require("Patient", ctx.src["PAT_ID"])
    def when(ctx):
        tz = fact(spec, "semantics", "timezone")[ctx.src["SITE"]]
        try: return local_time(ctx.src["DAY"], ctx.src["TIME"], tz)
        except ValueError as e:
            hold(ctx, "local_time", ctx.src["DAY"] + "|" + ctx.src["TIME"], f"Cannot establish UTC time: {e}. Need source log/offset; no first-fold assumption.")
            return None
    def annotate(ctx, out, overrides=None):
        explanations = {
            ("DocumentReference", "content"): "Delivered segments preserved exactly; upstream completeness cannot be established from a width pile-up.",
            ("MedicationRequest", "dosage"): "Original sig retained as text; no structured dose, route or frequency asserted.",
            ("Condition", "code"): "No verified code for this shorthand; original diagnosis text retained as unconfirmed.",
            ("Condition", "verificationStatus"): "Unmapped diagnosis preserved as text; cannot assert confirmed coding.",
            ("AllergyIntolerance", "substance"): "Source substance text preserved; no verified standard terminology mapping.",
            ("AllergyIntolerance", "criticality"): "Source lacks reliable severity/criticality; explicitly unable to assess.",
            ("Patient", "noKnownAllergies"): "Positive allergy conflicts with sticky NKA flag; preserve allergy and clear NKA per registration workflow.",
            ("Appointment", "end"): "30-minute duration from source guide; no independently charted end time.",
            ("Encounter", "class"): "Delivery is documented as outpatient ambulatory visits only.",
        }
        for field in out:
            klass = (overrides or {}).get(field, "transformed")
            ctx.note(field, klass, note=explanations.get((ctx.rtype, field), "Mapped by explicit Briar scenario adapter using discovered spec") if klass in {"degraded", "defaulted", "inferred"} else None)
        return out
    def map_patient(ctx):
        s = ctx.src
        if s["SEX"] not in {"M", "F", "U"}:
            hold(ctx, "sex", s["SEX"], "Unknown sex-at-birth code; need registration evidence.")
            return None
        if s["IDENTITY_CANDIDATES"]:
            ctx.decide("briar_identity_review", "|".join(s["IDENTITY_CANDIDATES"]),
                       "Matching demographics may be twins or duplicate charts. Keep source charts separate pending an identity audit; no automatic merge.",
                       [{"key": "keep_separate", "label": "Retain the distinct source charts pending identity audit"}],
                       blocking=False, default="keep_separate", context={"candidates": s["IDENTITY_CANDIDATES"], "synthetic": True})
        if not re.fullmatch(r"\d{8}", s["DOB"]):
            hold(ctx, "birth_date", s["DOB"] or "blank", "Birth date missing or century ambiguous; need chart evidence. Do not invent a date or choose an analyst's preferred pivot.")
            return None
        try: dob = datetime.strptime(s["DOB"], "%Y%m%d").date().isoformat()
        except ValueError:
            hold(ctx, "birth_date", s["DOB"], "Invalid source calendar date; need chart evidence.")
            return None
        family, given = s["NAME"].split(",", 1)
        out = {"identifiers": [{"system": "urn:briar:" + s["SITE"] + ":chart", "value": s["CHART"]}],
               "name": {"family": family, "given": [given]}, "birthDate": dob,
               "sexAtBirth": {"M": "male", "F": "female", "U": "unknown"}.get(s["SEX"], "unknown"),
               "noKnownAllergies": s["NKA"] == "Y" and not bool(s["ALLERGY"]), "active": True}
        ov = {"noKnownAllergies": "inferred"} if s["NKA"] == "Y" and s["ALLERGY"] else {}
        return annotate(ctx, out, ov)
    def map_encounter(ctx):
        pat, start = patient(ctx), when(ctx)
        status = {"F": "finished", "I": "in-progress"}.get(ctx.src["STATUS"])
        if status is None: hold(ctx, "visit_status", ctx.src["STATUS"], "Unknown visit status; need source owner.")
        return annotate(ctx, {"patient": pat, "class": "ambulatory", "status": status, "period": {"start": start}}, {"class": "inferred"})
    def map_condition(ctx):
        s = ctx.src
        if s["STATUS"] not in {"A", "R"}:
            hold(ctx, "condition_status", s["STATUS"], "Unknown condition status; do not assume resolved.")
            return None
        code = mapping["diagnosis"].get(s["CODE"])
        cc = {"coding": [{"system": "ICD-10-CM", "code": code}], "text": s["TEXT"]} if code else {"text": s["TEXT"]}
        return annotate(ctx, {"patient": patient(ctx), "code": cc, "clinicalStatus": "active" if s["STATUS"] == "A" else "resolved", "verificationStatus": "confirmed" if code else "unconfirmed"}, {"code": "standardized" if code else "degraded", "verificationStatus": "transformed" if code else "degraded"})
    def map_allergy(ctx):
        substance, reaction = ctx.src["ALLERGY"].split(":", 1)
        return annotate(ctx, {"patient": patient(ctx), "substance": {"text": substance}, "codingStatus": "uncoded",
                   "criticality": "unable-to-assess", "reactions": [{"manifestation": {"text": reaction}}]}, {"substance": "degraded", "criticality": "defaulted"})
    def map_medication(ctx):
        s = ctx.src
        code = mapping["medication"].get(s["DRUG"])
        if code is None:
            hold(ctx, "unmapped_medication", s["DRUG"], "No verified RxNorm match. Drug text and sig are archived; identify compound before target import.")
            return None
        status = fact(spec, "field:MED.TXT.STATUS", "convention").get(s["STATUS"])
        if status is None:
            hold(ctx, "med_status", s["STATUS"], "Unknown medication status; need pharmacy review.")
            return None
        return annotate(ctx, {"patient": patient(ctx), "medication": {"coding": [{"system": "RxNorm", "code": code}], "text": s["NAME"]}, "status": status,
                    "authoredOn": datetime.strptime(s["DAY"], "%Y%m%d").date().isoformat(), "dosage": {"text": s["SIG"]}, "dosageStructured": False}, {"medication": "standardized", "dosage": "degraded"})
    def map_observation(ctx):
        s = ctx.src
        if s["_withdrawn"]:
            ctx.note("record", "dropped", note="Source journal withdraws entire accession; no revision resurrected", original=s)
            return None
        rule = fact(spec, "field:LAB.TXT.RESULT", "convention")
        if s["RESULT"] == rule["missing_sentinel"]:
            ctx.note("record", "dropped", note="Documented no-result sentinel; no clinical measurement exists", original=s["RESULT"])
            return None
        code = mapping["lab"].get(s["TEST"])
        if code is None:
            hold(ctx, "lab_code", s["TEST"], "Unknown lab test; verified crosswalk required.")
            return None
        if s["STATUS"] not in {"F", "C", "P"}:
            hold(ctx, "result_status", s["STATUS"], "Unknown laboratory result status; need source audit.")
            return None
        out = {"patient": patient(ctx), "category": "laboratory", "code": {"coding": [{"system": "LOINC", "code": code}]}, "effective": when(ctx),
               "status": {"C": "corrected", "F": "final", "P": "preliminary"}[s["STATUS"]], "accession": s["SITE"] + "|" + s["ID"]}
        m = re.fullmatch(r"([<>]=?)?([+-]?\d+(?:\.\d+)?)([HL])?", s["RESULT"])
        if m:
            unit = s["UNIT"] or fact(spec, "semantics", "lab")["default_units"].get(s["TEST"])
            if not unit:
                hold(ctx, "lab_unit", s["TEST"] + "|" + s["SITE"], "Unit missing in mixed-device population. Cannot infer glucose units from magnitude or a site default.")
                return None
            out["valueQuantity"] = {"value": float(m[2]), "unit": unit}
            if m[1]: out["valueQuantity"]["comparator"] = m[1]
            if m[3]: out["interpretation"] = {"H": "high", "L": "low"}[m[3]]
        elif s["RESULT"] == "NEG": out["valueCodeable"] = rule["NEG"]
        else: out["valueString"] = s["RESULT"]
        return annotate(ctx, out, {"code": "standardized"})
    def map_note(ctx):
        return annotate(ctx, {"patient": patient(ctx), "type": {"coding": [{"system": "LOINC", "code": fact(spec, "semantics", "note_type")}]},
                  "date": when(ctx), "contentType": "text/plain", "content": ctx.src["TEXT"]}, {"content": "degraded"})
    def map_appointment(ctx):
        status = fact(spec, "semantics", "appointment_known").get(ctx.src["STATUS"])
        if status is None:
            hold(ctx, "appointment_status", ctx.src["STATUS"], "R has conflicting meanings (rescheduled/arrived); scheduling audit required. No invented Nimbus status.")
            return None
        start = when(ctx)
        return annotate(ctx, {"patient": patient(ctx), "status": status, "start": start, "end": (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z") if start else None}, {"end": "inferred"})
    def map_charge(ctx):
        s = ctx.src
        rule = fact(spec, "field:BILL.TXT.AMOUNT", "convention")
        raw = Decimal(s["AMOUNT"])
        if raw < 0:
            hold(ctx, "credit", s["SITE"], "Source credit cannot be represented by Nimbus ChargeItem; need a credit workflow. Do not flip the sign.")
            return None
        scale = 1 if s["SITE"] == rule["site"] and s["DAY"] >= rule["dollars_from_service_date"] else 100
        code = mapping["charge"].get(s["CODE"])
        if not code:
            hold(ctx, "charge_code", s["CODE"], "Unknown charge code; billing crosswalk needed.")
            return None
        return annotate(ctx, {"patient": patient(ctx), "encounter": ctx.require("Encounter", s["SITE"] + "|" + s["VISIT"]), "code": {"coding": [{"system": "CPT", "code": code}]},
                   "amount": float(raw / scale), "units": 1, "serviceDate": datetime.strptime(s["DAY"], "%Y%m%d").date().isoformat()}, {"code": "standardized"})
    funcs = [map_patient, map_encounter, map_condition, map_allergy, map_medication, map_observation, map_note, map_appointment, map_charge]
    original = {rt: MAPPERS[rt] for rt in TYPES}
    MAPPERS.update(dict(zip(TYPES, funcs)))
    return profile, state, original
