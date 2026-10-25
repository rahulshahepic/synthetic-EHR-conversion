"""Spec generation: ledger + claims -> the declarative import spec.

The PRIMARY output is the declarative spec (JSON-able dict): a list of
rules, each with provenance — kind (dictionary | analyst | profiler-data |
policy) plus a reference — and a ``data_confirmed`` flag that is true only
when profiler observations (directly, or as a dispute resolution) back the
rule. The generated Python profile is a thin rendering of that spec, never
the artifact of record.

Pure function: same ledger + claims in, byte-identical spec out.

One rule is policy, not evidence, and overrides any claim: identity merges
route to a human reconciliation question, never an auto-merge rule — even
when an analyst describes merging as routine. The overridden claim stays
visible in the spec's ``policy_overrides``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .claims import ClaimStore
from .ledger import LedgerEvent

PROFILE_CONSTANTS: dict[tuple[str, str], str] = {
    ("profile", "system_org"): "SYSTEM_ORG",
    ("profile", "mrn_system"): "MRN_SYSTEM",
    ("profile", "facility_tz"): "FACILITY_TZ",
    ("profile", "default_tz"): "DEFAULT_TZ",
    ("profile", "vital_units"): "VITAL_UNITS",
    ("profile", "charge_cents_from"): "CHARGE_CENTS_FROM",
    ("profile", "lab_feed_only_days"): "LAB_FEED_ONLY_DAYS",
    ("profile", "pivot_year"): "PIVOT_YEAR",
}

MERGE_POLICY_RULE = {
    "id": "SAFETY-IDENTITY-MERGE",
    "kind": "identity_policy",
    "subject": "identity",
    "predicate": "merge_policy",
    "value": "route_to_reconciliation",
    "provenance": {"kind": "policy", "ref": "docs/socratic-import-builder.md"},
    "data_confirmed": False,
    "note": "Identity merges always require a human reconciliation decision. "
            "No claim, from any source, can turn this into an auto-merge rule.",
}


def _provenance_of(source: str) -> tuple[str, bool]:
    """(kind, data_confirmed) for a claim's provenance string (or a dispute
    provenance string of the form '<winner source>; dispute resolved via X')."""
    s = source or ""
    data_confirmed = "OBS-" in s or "profiler" in s.lower()
    if s.startswith("ledger:"):
        kind = "analyst"
    elif "OBS-" in s or "profiler" in s.lower():
        kind = "profiler-data"
    elif "dict" in s.lower() or "DATADICT" in s:
        kind = "dictionary"
    else:
        kind = "analyst" if "ledger" in s else "dictionary"
    return kind, data_confirmed


@dataclass
class SpecPackage:
    source: str
    spec: dict[str, Any]                # the artifact of record (JSON-able)
    profile_code: str                   # thin rendering of the spec
    crosswalks: dict[str, str]          # code set name -> CSV text
    reader_binding: dict[str, Any]

    def spec_json(self) -> str:
        return json.dumps(self.spec, indent=1, sort_keys=True) + "\n"


def generate_spec(events: list[LedgerEvent], store: ClaimStore, source: str) -> SpecPackage:
    rules: list[dict[str, Any]] = []
    overrides: list[dict[str, Any]] = []
    keys = sorted({c.key() for c in store.claims})
    n = 0
    for subject, predicate in keys:
        value = store.resolved_value(subject, predicate)
        prov_str = store.provenance(subject, predicate)
        if subject == "identity" and predicate == "merge_policy":
            claimed = [c.value for c in store.get(subject, predicate)]
            if any(v != "route_to_reconciliation" for v in claimed):
                overrides.append({"subject": subject, "predicate": predicate,
                                  "claimed_values": claimed,
                                  "policy": "route_to_reconciliation"})
            continue  # the policy rule below replaces any claim on this key
        if value is None and store.dispute(subject, predicate) is not None:
            continue  # unresolved dispute -> known unknown, not a rule
        if value is None:
            continue
        kind, confirmed = _provenance_of(prov_str or "")
        n += 1
        rules.append({
            "id": f"R{n:03d}",
            "kind": "fact",
            "subject": subject,
            "predicate": predicate,
            "value": value,
            "provenance": {"kind": kind, "ref": prov_str},
            "data_confirmed": confirmed,
        })
    rules.append(dict(MERGE_POLICY_RULE))

    known_unknowns: list[dict[str, Any]] = []
    for d in sorted(store.unresolved_disputes(), key=lambda d: (d.subject, d.predicate)):
        known_unknowns.append({
            "subject": d.subject, "predicate": d.predicate,
            "claimed_values": d.values,
            "disposition": "runtime_question",
        })
    known_unknowns.append({
        "subject": "identity", "predicate": "merge_decisions",
        "disposition": "runtime_question",
        "note": "Every proposed identity merge is decided by a human in "
                "reconciliation; the spec contains no auto-merge rule.",
    })

    reader_name = store.resolved_value("profile", "reader") or "fixed_width"
    binding = _reader_binding(rules, source, reader_name)
    spec = {
        "source": source,
        "generator": "bridge.interview.specgen",
        "ledger_events": len(events),
        "rules": rules,
        "known_unknowns": known_unknowns,
        "policy_overrides": overrides,
        "reader_binding": binding,
    }
    return SpecPackage(source=source, spec=spec,
                       profile_code=_render_profile(source, rules, known_unknowns, reader_name),
                       crosswalks=_render_crosswalks(rules),
                       reader_binding=binding)


def _reader_binding(rules: list[dict[str, Any]], source: str, reader_name: str) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for rule in rules:
        if rule["predicate"] == "layout_binding" and rule["subject"].startswith("file:"):
            files[rule["subject"][len("file:"):]] = rule["value"]
    return {"source": source, "reader": reader_name, "files": files}


def _render_crosswalks(rules: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rule in rules:
        if rule["subject"].startswith("codeset:") and rule["predicate"] == "crosswalk":
            name = rule["subject"][len("codeset:"):]
            value = rule["value"]
            rows = value.items() if isinstance(value, dict) else value
            lines = ["source,target,provenance"]
            for src, tgt in sorted(rows):
                lines.append(f"{src},{tgt},{rule['provenance']['kind']}:{rule['provenance']['ref']}")
            out[name] = "\n".join(lines) + "\n"
    return out


def _render_profile(source: str, rules: list[dict[str, Any]],
                    known_unknowns: list[dict[str, Any]],
                    reader_name: str = "fixed_width") -> str:
    by_const: dict[str, dict[str, Any]] = {}
    for rule in rules:
        const = PROFILE_CONSTANTS.get((rule["subject"], rule["predicate"]))
        if const:
            by_const[const] = rule
    lines = [
        f'"""GENERATED profile for {source} by the Socratic import builder.',
        "",
        "Artifact of record: the declarative spec (spec.json) this was rendered",
        "from. Do not edit by hand; re-run the interview/spec generation.",
        '"""',
    ]
    if "CHARGE_CENTS_FROM" in by_const:
        lines.append("from datetime import date")
    lines.append("")
    lines.append(f"SOURCE_SYSTEM = {source!r}")
    lines.append(f'READER = "{reader_name}"')
    for const in sorted(by_const):
        rule = by_const[const]
        value = rule["value"]
        if const == "CHARGE_CENTS_FROM" and isinstance(value, str):
            y, m, d = (int(x) for x in value.split("-"))
            expr = f"date({y}, {m}, {d})"
        else:
            expr = repr(value)
        lines.append(f"# provenance: {rule['provenance']['kind']} — {rule['provenance']['ref']}"
                     f" (data_confirmed={rule['data_confirmed']})")
        lines.append(f"{const} = {expr}")
    lines.append("")
    lines.append("# Known unknowns: unresolved at generation time. Each becomes a")
    lines.append("# runtime reconciliation question, never a silent default.")
    lines.append(f"KNOWN_UNKNOWNS = {known_unknowns!r}")
    lines.append("")
    lines.append("# Identity merges require a human decision (policy; see spec).")
    lines.append('MERGE_POLICY = "route_to_reconciliation"')
    return "\n".join(lines) + "\n"
