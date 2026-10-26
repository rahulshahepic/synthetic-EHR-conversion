"""Reproducible discovery transcript and structured claims; never reads fixture truth.

The questions reflect the autonomous interview conducted on Oct 26. Stub
answers come only through ask(). This is an authored rehearsal, not a blinded
evaluation of discovery by an independent model.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from bridge.interview.ledger import append_event, read_events
from bridge.interview.profiler import parse_layouts_dat
from bridge.interview.reader import FixedWidthExport, stage_records
from testbed.scenarios.briar_service import service
from .briar_interview import ask, emit, init

INITIAL = [
    ("systems", "Is the old dictionary current on identity, DOB, timestamps, money and appointment R?", "Establish the systems owner's position."),
    ("registration", "Is CHART enterprise-wide, and may identical demographics be merged?", "Repeated chart numbers and separate installations challenge enterprise identity."),
    ("registration", "How are DOB and no-known-allergy flags actually used?", "DOB shapes and allergy conflicts require their operational owner."),
    ("lab", "Are all glucose units now mmol/L at Outreach?", "A scheduled migration does not establish that every device changed."),
    ("pharmacy", "What does MED H mean, and can MISC be skipped?", "Version skew and missing drug mappings can lose active therapy."),
    ("billing", "Are all BILL amounts cents and can credits be imported as charges?", "Decimal and negative amounts contradict a global cents rule."),
]
FOLLOWUP = [
    ("systems", "The support note and data conflict with that guide; which delivery contract applies?", "The 3.7 layout conflicts with the approved 2.3 guide."),
    ("systems", "Registration says current DOB is YYYYMMDD and CHART is site-scoped; do you have contrary delivery evidence?", "Ask for evidence rather than settle by seniority."),
    ("registration", "Can you establish the century for six-digit DOBs or prove the matching charts are one person?", "Name and date shape prove neither identity nor century."),
    ("lab", "The B data still contains mg/dL; what supports ignoring it?", "Measured B-site rows contradict the initial blanket unit claim."),
    ("lab", "What do nonnumeric results, 999999, suffix flags, revisions and journal deletes mean?", "Distinguish valid text, missing values, corrections and withdrawals."),
    ("lab", "Can missing lab units always be filled from the dictionary?", "A mixed-device population invalidates a universal glucose default."),
    ("pharmacy", "Does the same H meaning apply to old archived medication exports?", "Limit the rule to the supported version."),
    ("systems", "What is APPT R in the current delivery?", "Physical shapes cannot establish a status meaning."),
    ("systems", "Are full-width note segments necessarily truncated, and how do journal deletions apply?", "Full width is not proof of lost text; establish assembly and delete scope."),
]


def discover(root: Path) -> dict:
    if (root / "ledger.jsonl").exists():
        raise ValueError("a discovery run is append-only; use a fresh output directory")
    initial = init(root)
    report = json.loads((root / "profile_report.json").read_text())
    svc = service(root / "source")
    layouts, _ = parse_layouts_dat(svc.read_estate("LAYOUTS.DAT")["text"])
    ledger = root / "ledger.jsonl"
    def event(typ, **payload): return append_event(ledger, typ, payload)
    def claim(subject, predicate, value, source, kind="dictionary", refs=()):
        return event("claim", subject=subject, predicate=predicate, value=value, source=source,
                     source_kind=kind, confidence=0.95 if kind == "analyst" else 0.8, evidence_refs=list(refs))
    def resolve(subject, predicate, value, why, refs=()):
        return event("resolve", subject=subject, predicate=predicate, value=value, source=why,
                     claimed_by="interviewer:ChatGPT (synthetic rehearsal)", source_kind="analyst", evidence_refs=list(refs))
    key_fields = {"REG": ["SITE", "CHART"], "LAB": ["SITE", "ID", "TEST", "REV"],
                  "NOTE": ["SITE", "ID", "SEQ"], "JRN": ["SITE", "SEQ"]}
    binding = {"source": "briar", "files": {}}
    for stem, per_rt in layouts.items():
        spec = {"path": stem + ".TXT", "discriminator": {"start": 0, "width": 2},
                "key_fields": key_fields.get(stem, ["SITE", "ID"]),
                "layouts": {rt: [asdict(f) for f in fields] for rt, fields in per_rt.items()}}
        binding["files"][stem] = spec
        claim("file:" + stem, "layout_binding", spec, "LAYOUTS.DAT v3.7; key choices pending interviews")
    rows = stage_records(FixedWidthExport(root / "source", binding))
    by_type = {}
    for row in rows: by_type.setdefault(row["record_type"], []).append(row)
    # Observations below are computed from delivery rows, never assertions from an interview.
    measurements = {
        "cross_site_chart_collisions": len({r["payload"]["CHART"] for r in by_type["REG"]}),
        "registrations": len(by_type["REG"]),
        "dob_lengths": dict(Counter(len(r["payload"]["DOB"]) for r in by_type["REG"])),
        "lab_units_by_site": {s: dict(Counter(r["payload"]["UNIT"] for r in by_type["LAB"] if r["payload"]["SITE"] == s and r["payload"]["TEST"] == "GLU")) for s in "AB"},
        "bill_amounts_by_site_and_era": {f"{s}:{era}": sorted({r["payload"]["AMOUNT"] for r in by_type["BILL"] if r["payload"]["SITE"] == s and (r["payload"]["DAY"] >= "20260101") == era}) for s in "AB" for era in (False, True)},
        "nka_positive_conflicts": sum(r["payload"]["NKA"] == "Y" and bool(r["payload"]["ALLERGY"]) for r in by_type["REG"]),
    }
    event("analysis", source="generated binding applied to delivery data", measurements=measurements)
    (root / "evidence.json").write_text(json.dumps(measurements, indent=2, sort_keys=True))
    assert measurements["cross_site_chart_collisions"] < measurements["registrations"]
    assert "mg/dL" in measurements["lab_units_by_site"]["B"]
    # Record the mostly-correct dictionary, including its wrong claims.
    initial_conventions = {"field:REG.TXT.DOB": "YYMMDD; pivot=50", "field:MED.TXT.STATUS": {"A": "active", "S": "stopped", "H": "historical_skip"},
        "field:LAB.TXT.RESULT": "numeric_with_optional_flag", "field:LAB.TXT.UNIT": "row_unit_overrides_dictionary",
        "field:BILL.TXT.AMOUNT": "all_cents", "field:APPT.TXT.STATUS": {"B": "booked", "C": "cancelled", "R": "rescheduled"}}
    for subj, val in initial_conventions.items(): claim(subj, "convention", val, "DATADICT.TXT v2.3")
    claim("identity", "keying_story", {"key_fields": ["REG.TXT.CHART"], "master_index": False}, "DATADICT.TXT v2.3")
    received = {}
    for analyst, question, reason in INITIAL:
        got = ask(root, analyst, question, reason)
        received[question] = got
    # Preserve initial, confidently wrong analyst assertions as disputes.
    claim("identity", "keying_story", {"key_fields": ["REG.TXT.SITE+REG.TXT.CHART"], "master_index": False}, "ledger:" + received[INITIAL[1][1]]["answer_event"], "analyst")
    claim("identity", "merge_policy", "auto_merge_obvious_demographic_matches", "ledger:" + received[INITIAL[1][1]]["answer_event"], "analyst")
    claim("field:LAB.TXT.UNIT", "convention", "all_B_glucose_mmol/L_ignore_row_units", "ledger:" + received[INITIAL[3][1]]["answer_event"], "analyst")
    claim("field:REG.TXT.DOB", "convention", "YYYYMMDD_or_YYMMDD_pivot30", "ledger:" + received[INITIAL[2][1]]["answer_event"], "analyst")
    for analyst, question, reason in FOLLOWUP:
        got = ask(root, analyst, question, reason)
        received[question] = got
    def from_answer(question, subject, predicate, value, why=""):
        ref = received[question]["answer_event"]
        claim(subject, predicate, value, "ledger:" + ref, "analyst", [ref])
        resolve(subject, predicate, value, why or "Follow-up with domain owner; delivery evidence checked", [ref])
    from_answer(FOLLOWUP[1][1], "identity", "keying_story", {"key_fields": ["REG.TXT.SITE+REG.TXT.CHART"], "master_index": False}, "Systems withdrew old enterprise-ID assertion; registration and site collisions agree. No patient merges authorized.")
    from_answer(FOLLOWUP[2][1], "field:REG.TXT.DOB", "convention", {"format": "YYYYMMDD", "other": "runtime_question"}, "Eight-digit rows parse; six-digit century and missing dates cannot be established.")
    from_answer(FOLLOWUP[3][1], "field:LAB.TXT.UNIT", "convention", "row_unit_overrides_dictionary", "Initial blanket site conversion was contradicted by B-site unit labels and withdrawn.")
    from_answer(INITIAL[4][1], "field:MED.TXT.STATUS", "convention", {"A": "active", "S": "stopped", "H": "on-hold"}, "Pharmacy confirms current 3.7 delivery only; archived H remains out of scope.")
    from_answer(INITIAL[5][1], "field:BILL.TXT.AMOUNT", "convention", {"site": "B", "dollars_from_service_date": "20260101", "otherwise": "cents", "negative": "runtime_question"})
    from_answer(FOLLOWUP[4][1], "field:LAB.TXT.RESULT", "convention", {"numeric_flags": True, "NEG": "negative", "missing_sentinel": "999999", "comparator": "preserve", "other_text": "preserve"})
    claim("field:APPT.TXT.STATUS", "convention", {"B": "booked", "C": "cancelled", "R": "arrived"}, "ledger:" + received[FOLLOWUP[7][1]]["answer_event"], "analyst")
    # Deliberately unresolved: no scheduling analyst, no authoritative status audit.
    semantic = {
        "timezone": {"A": "America/Chicago", "B": "America/Chicago", "ambiguous_or_nonexistent": "runtime_question", "2400": "next_midnight"},
        "allergy": {"positive_overrides_NKA": True, "substance_reaction_separator": ":"},
        "lab": {"latest": "max_numeric_revision", "deletion": "entire_site_accession", "default_units": {"K": "mmol/L"}, "missing_glucose_unit": "runtime_question"},
        "notes": {"group": ["SITE", "ID"], "order": "numeric_SEQ", "whitespace": "right_trim_only", "upstream_truncation": "unknown"},
        "appointment_known": {"B": "booked", "C": "cancelled"},
    }
    semantic_sources = {"timezone": FOLLOWUP[0][1], "allergy": INITIAL[2][1], "lab": FOLLOWUP[4][1], "notes": FOLLOWUP[8][1], "appointment_known": FOLLOWUP[7][1]}
    for name, val in semantic.items():
        q = semantic_sources[name]
        claim("semantics", name, val, "ledger:" + received[q]["answer_event"], "analyst", [received[q]["answer_event"]])
    code_sets = {"lab": {"GLU": "2345-7", "K": "2823-3", "CULT": "630-4"}, "medication": {"MET": "860975"}, "diagnosis": {"DM2": "E11.9"}, "charge": {"OFFICE": "99213"}}
    for cs, val in code_sets.items(): claim("codeset:" + cs, "crosswalk", val, "CROSSWALKS.TXT synthetic edition 3.7")
    claim("semantics", "note_type", "11506-3", "CROSSWALKS.TXT")
    # Cover each actual field by a meaningful convention. Administrative tokens
    # have explicit string passthrough; clinical status/date/result rules above
    # keep their own unresolved state and are not papered over by passthrough.
    meaningful = {"DAY": "YYYYMMDD", "TIME": "local_HHMM_with_2400_and_DST_review", "NAME": "LAST,FIRST (except medication name, which is text)",
        "SEX": "M/F/U", "NKA": "sticky_Y_requires_positive_allergy_check", "ALLERGY": "substance:reaction_text",
        "REV": "integer_max_wins", "SEQ": "integer_order", "SIG": "clinician_text_preserve_verbatim",
        "TEXT": "right_trim_padding_only_preserve_content", "STATUS": "source_domain_status; unknowns_require_review",
        "AMOUNT": "service_date_and_site_specific", "DOB": "unknown_dates_require_review"}
    special = set(initial_conventions)
    for fn, data in report["files"].items():
        for fld in data["fields"]:
            subj = f"field:{fn}.{fld}"
            if subj in special: continue
            if fld in meaningful: claim(subj, "convention", meaningful[fld], "DATADICT.TXT v2.3 + SUPPORT.TXT 3.7; clarified interviews recorded")
            else: claim(subj, "pass_through_text", "opaque_source_token_preserve_without_clinical_inference", "LAYOUTS.DAT v3.7")
    event("limitation", text="Native builder generates facts/bindings, not domain mappers. The scenario adapter is explicitly authored from these claims. This is one model authoring and testing its fixture, not blinded discovery. No runtime answers or sign-offs may impersonate Rahul.")
    result = emit(root)
    (root / "discovery_ledger.jsonl").write_bytes(ledger.read_bytes())
    transcript = ["# Briar discovery transcript", "", "Synthetic deterministic analysts; fixture and interview authored by the same assistant. No claim of a blinded evaluation.", ""]
    for ev in read_events(ledger):
        if ev.type == "question": transcript += [f"**{ev.id} · interviewer → {ev.payload['analyst']}**", "", ev.payload["text"], "", "Reason: " + ev.payload["why"], ""]
        if ev.type == "answer": transcript += [f"**{ev.id} · simulated {ev.payload['analyst']}**", "", ev.payload["text"], ""]
        if ev.type == "resolve": transcript += [f"**{ev.id} · resolution: {ev.payload['subject']} / {ev.payload['predicate']}**", "", json.dumps(ev.payload["value"], sort_keys=True), "", ev.payload["source"], ""]
    (root / "INTERVIEW.md").write_text("\n".join(transcript))
    return result
