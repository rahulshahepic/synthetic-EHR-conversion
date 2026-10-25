"""Spec generation: ledger + claims -> the declarative import spec.

The PRIMARY output is the declarative spec (JSON-able dict): a list of
rules, each with provenance — kind (dictionary | analyst | profiler-data |
policy) plus a reference — and a ``data_confirmed`` flag that is true only
when profiler observations (directly, or as a dispute resolution) back the
rule. The generated Python profile is a thin rendering of that spec, never
the artifact of record.

Provenance is derived from validated evidence, never from substring
matching on free-text source strings. A rule is ``profiler-data`` only
when the claim that stated its value (or the resolution that settled it)
carries structured profiler evidence, and ``data_confirmed`` is true only
when a cited observation id resolves to an actual profiler observation
recorded in the ledger — an ``OBS-<digits>`` event with non-empty stats.
A document quote recorded under an observation-like id (an estate note,
a dictionary excerpt) is document evidence: it can inform a resolution,
but it never confirms anything and never earns the profiler-data kind.

Pure function: same ledger + claims in, byte-identical spec out.

One rule is policy, not evidence, and overrides any claim: identity merges
route to a human reconciliation question, never an auto-merge rule — even
when an analyst describes merging as routine. The override applies to
every identity claim other than the keying story, whatever predicate it
arrives under. The overridden claim stays visible in the spec's
``policy_overrides``.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Any

from .claims import Claim, ClaimStore, Dispute, _canon
from .coverage import Inventory, build_checklist, uncovered
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


_OBS_DATA_ID = re.compile(r"^OBS-\d+$")
_OBS_TOKEN = re.compile(r"OBS-[A-Za-z0-9_-]+")


def _observation_stats(events: list[LedgerEvent]) -> dict[str, dict[str, Any]]:
    """Observation id -> stats, for every observation recorded in the ledger."""
    out: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.type == "observation":
            oid = e.payload.get("obs_id")
            if oid:
                out[oid] = e.payload.get("stats") or {}
    return out


def _is_data_observation(ref: str, observations: dict[str, dict[str, Any]]) -> bool:
    """A reference is profiler *data* evidence only if it names an actual
    profiler observation recorded in the ledger: an ``OBS-<digits>`` id
    whose event carries non-empty stats. Document quotes filed under
    observation-like ids (``OBS-ESTATE-1``, ``OBS-VERSION``) fail this —
    deliberately."""
    return bool(_OBS_DATA_ID.match(ref or "")) and bool(observations.get(ref))


def _claim_kind(claim: Claim, observations: dict[str, dict[str, Any]]) -> str:
    """The provenance kind of one claim, from its structured provenance
    when recorded, else from a conservative reading of its source: an exact
    data-observation source is profiler-data, a ledger answer is an
    analyst, an estate document (dictionary, layouts, interface notes) is
    dictionary evidence. Free text merely *mentioning* an observation or
    the profiler earns nothing."""
    if claim.source_kind:
        return claim.source_kind
    src = claim.source or ""
    first = src.split()[0].rstrip("(:") if src.split() else ""
    if _is_data_observation(first, observations):
        return "profiler-data"
    if src.startswith("ledger:"):
        return "analyst"
    low = src.lower()
    if low.startswith("profiler"):
        return "profiler-data"
    if any(mark in low for mark in ("dictionary", "datadict", "estate",
                                    "layouts", "interface notes")):
        return "dictionary"
    return "analyst"


def _evidence_confirmed(refs: Any, observations: dict[str, dict[str, Any]]) -> bool:
    return any(_is_data_observation(r, observations) for r in refs)


def _rule_provenance(store: ClaimStore, subject: str, predicate: str, value: Any,
                     observations: dict[str, dict[str, Any]]) -> tuple[str, bool, str | None]:
    """(kind, data_confirmed, ref) for a rule, derived from validated evidence.

    The kind is the kind of the claim that stated the winning value (the
    claim is what the rule asserts); when no claim states the resolved
    value (a resolution introduced it), the resolution's own kind decides.
    ``data_confirmed`` is kept separate from who claimed the value: an
    analyst's claim confirmed by a profiler observation is analyst-kind
    and data-confirmed.
    """
    dispute = store.dispute(subject, predicate)
    winners = [c for c in store.get(subject, predicate)
               if _canon(c.value) == _canon(value)]
    kind: str | None = None
    confirmed = False
    if winners:
        kind = _claim_kind(winners[0], observations)
        for c in winners:
            refs = list(c.evidence_refs)
            if c.source and c.source.split():
                refs.append(c.source.split()[0].rstrip("(:"))
            if _evidence_confirmed(refs, observations):
                confirmed = True
    if dispute is not None and dispute.resolved:
        refs = list(dispute.resolution_evidence_refs)
        if not refs and dispute.resolution_source:
            refs = _OBS_TOKEN.findall(dispute.resolution_source)
        if _evidence_confirmed(refs, observations):
            confirmed = True
        if kind is None:
            kind = dispute.resolution_source_kind or (
                "profiler-data" if _evidence_confirmed(refs, observations) else "analyst")
    return kind or "analyst", confirmed, store.provenance(subject, predicate)


def _with_extra_claims(store: ClaimStore, extra: list[Claim]) -> ClaimStore:
    """A copy of ``store`` with additional claims folded in (the original
    store is left untouched, keeping generate_spec a pure function)."""
    new = ClaimStore()
    new.claims = list(store.claims)
    new.disputes = {
        key: Dispute(subject=d.subject, predicate=d.predicate, claims=list(d.claims),
                     resolved_value=d.resolved_value,
                     resolution_source=d.resolution_source,
                     resolution_claimed_by=d.resolution_claimed_by,
                     resolution_source_kind=d.resolution_source_kind,
                     resolution_evidence_refs=d.resolution_evidence_refs)
        for key, d in store.disputes.items()
    }
    for c in extra:
        new.add(c)
    return new


@dataclass
class SpecPackage:
    source: str
    spec: dict[str, Any]                # the artifact of record (JSON-able)
    profile_code: str                   # thin rendering of the spec
    crosswalks: dict[str, str]          # code set name -> CSV text
    reader_binding: dict[str, Any]

    def spec_json(self) -> str:
        return json.dumps(self.spec, indent=1, sort_keys=True) + "\n"


def generate_spec(events: list[LedgerEvent], store: ClaimStore, source: str,
                  inventory: Inventory | None = None,
                  profile_report: dict[str, Any] | None = None) -> SpecPackage:
    """Build the spec package from a ledger and its claim store.

    ``inventory`` (the coverage checklist's view of the export) is carried
    into the spec: every checklist item the claims leave open or disputed
    appears in ``known_unknowns`` instead of being silently dropped.
    ``profile_report`` (a profiler report over the export) contributes
    profiler value-shape claims, so a data-observed value shape can
    dispute an analyst's contrary belief instead of being swallowed.
    """
    if profile_report is not None:
        from .profiler import value_shape_claims
        extra = value_shape_claims(profile_report)
        if extra:
            store = _with_extra_claims(store, extra)
    observations = _observation_stats(events)
    rules: list[dict[str, Any]] = []
    overrides: list[dict[str, Any]] = []
    keys = sorted({c.key() for c in store.claims})
    n = 0
    for subject, predicate in keys:
        if subject == "identity" and predicate != "keying_story":
            # Merge policy is policy, not evidence — for ANY predicate that
            # expresses it, not only the one literally named merge_policy.
            claimed = [c.value for c in store.get(subject, predicate)]
            if any(v != "route_to_reconciliation" for v in claimed):
                overrides.append({"subject": subject, "predicate": predicate,
                                  "claimed_values": claimed,
                                  "policy": "route_to_reconciliation"})
            continue  # the policy rule below replaces any claim on this key
        value = store.resolved_value(subject, predicate)
        if value is None:
            continue  # unresolved / null-resolved dispute -> known unknown
        kind, confirmed, prov_str = _rule_provenance(
            store, subject, predicate, value, observations)
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
    seen_unknowns: set[tuple[str, str]] = set()

    def add_unknown(subject: str, predicate: str, **kw: Any) -> None:
        if (subject, predicate) in seen_unknowns:
            return
        seen_unknowns.add((subject, predicate))
        known_unknowns.append({"subject": subject, "predicate": predicate, **kw})

    open_disputes = sorted(
        store.unresolved_disputes() + store.null_resolved_disputes(),
        key=lambda d: (d.subject, d.predicate))
    for d in open_disputes:
        entry: dict[str, Any] = {"claimed_values": d.values,
                                 "disposition": "runtime_question"}
        if d.resolved:  # resolved to None: "absent" was the resolution
            entry["resolved_value"] = None
            entry["note"] = ("dispute resolved to absent (None); the subject "
                              "stays visible as a known unknown rather than "
                              "vanishing from the spec")
        add_unknown(d.subject, d.predicate, **entry)
    if inventory is not None:
        for item in uncovered(build_checklist(inventory, store)):
            add_unknown(item.subject, item.predicate, claimed_values=[],
                        disposition="runtime_question",
                        note=f"coverage checklist item {item.id} is {item.status}: "
                             f"{item.description}")
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
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            writer.writerow(["source", "target", "provenance"])
            for src, tgt in sorted(rows):
                writer.writerow([src, tgt, f"{rule['provenance']['kind']}:"
                                            f"{rule['provenance']['ref']}"])
            out[name] = buf.getvalue()
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
