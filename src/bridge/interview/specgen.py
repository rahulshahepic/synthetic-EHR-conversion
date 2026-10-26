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
recorded in the ledger — an ``OBS-<digits>`` event with non-empty stats —
*and* that observation is about this rule's subject: a ``field:`` subject
names its file and field in the subject itself, and any other subject
confirms only through the binding recorded for the (subject, predicate)
itself — a ledger ``binding`` event, recorded once per
(subject, predicate) with its own evidence, and itself backed by a
cited observation describing the bound field (a binding event with no
such evidence, or a conflicting rebind, confirms nothing). A binding is never carried on a claim or a resolution, so no
claim can bind itself to whatever observation it cites. The generator
carries no per-source binding table, so a subject from a new source can
be confirmed as soon as its interview records the binding. An
observation about some other field confirms nothing here, however real
it is. A document quote
recorded under an observation-like id (an estate note, a dictionary
excerpt) is document evidence: it can inform a resolution, but it never
confirms anything and never earns the profiler-data kind. Resolutions
confirm only through their structured ``evidence_refs``; observation
ids mentioned in a resolution's free-text source string earn nothing.

Pure function: same ledger + claims in, byte-identical spec out.

One rule is policy, not evidence, and overrides any claim: identity merges
route to a human reconciliation question, never an auto-merge rule — even
when an analyst describes merging as routine. The override applies to
every identity claim other than the keying story, whatever predicate it
arrives under. The overridden claim stays visible in the spec's
``policy_overrides``. The keying story itself is a fact (how charts are
keyed), and it is a *structured* value — the key fields, whether a
master index exists, and whether registration creates true duplicate
charts — never a sentence: there is nowhere in that shape for an
instruction to hide. A keying claim that arrives as free text (or
a malformed structure) is not a keying fact at all: it is flagged in
``policy_overrides`` and the subject surfaces as a known unknown, so the
spec never carries an unflagged auto-merge instruction, whatever
predicate it arrived under.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Any

from .claims import (Claim, ClaimStore, Dispute, is_data_observation,
                     observation_confirms, observation_payloads,
                     values_match)
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


# A key field in a structured keying story: a field reference, or a
# ``+`` composite of field references (``REG.TXT.SSN4+REG.TXT.DOB``).
# A bare grammar cannot keep an instruction out on its own — an
# uppercase token like ``AUTO_MERGE.ALL_CHARTS`` is shaped exactly like
# a field reference — so a reference validates only when machine
# evidence establishes that the field exists in that file: the
# profiler's inventory of the export, or its data observations.
# The check is per file: a token naming a file with no estate evidence
# behind it does not validate, however it is shaped (``MERGE.ALL``,
# ``AUTO_MERGE.ALL.CHARTS_SHARING_SSN4_WITHOUT_REVIEW``), and an
# interview that has observed REG.TXT.DOB has NOT thereby established
# that REG.TXT.ACCT exists. Until the evidence exists the story stays
# flagged as a known unknown instead of becoming a rule. Lowercase,
# hyphens and free words fail too, so an instruction
# ("auto-merge-any-two-charts-...") cannot hide inside a single token
# the way it could when only whitespace was banned.


def _known_fields(events: list[LedgerEvent],
                  observations: dict[str, dict[str, Any]],
                  inventory: Inventory | None) -> dict[str, set[str]]:
    """The estate's real fields, keyed by file: ``FILE -> {FIELD}``,
    from machine evidence only: the profiler's inventory of the export
    (recorded in the ledger as an ``inventory`` event, or passed in as
    the coverage ``inventory``) and the profiler's data observations.

    No claim or resolution feeds it, whatever its kind, source or
    evidence refs. A layout claim's kind is a label written into the
    ledger alongside the claim; letting it count meant every round of
    review found another way to label an interviewee's invented layout
    (``AUTO_MERGE.ALL``) as estate truth so that its keying story would
    validate. The inventory is what the profiler found when it read the
    export's data with the estate's own layouts file, so a field is
    known exactly when the data has it (the dictionary's stale FAX
    field is not). A document quote filed under an observation-like id
    is not data either: only observations that pass the
    data-observation test contribute their (file, field).

    Trust boundary: generation cannot authenticate a ledger event. An
    ``inventory`` or data ``observation`` event is believed because of
    WHO writes those event types — the profiler, via the runner, from
    the export's data — never because of anything an interview can
    say. Interview content (answers, and the claims and resolutions
    drawn from them) never becomes an inventory or observation event.
    A hand-written inventory or observation event would mint fields;
    for a committed ledger, the acceptance test that re-profiles the
    export and requires the recorded inventory to match exactly is the
    check that catches that. What this function guarantees is that no
    claim or resolution, however labelled, can add a field."""
    by_file: dict[str, set[str]] = {}

    def feed(file: Any, field: Any) -> None:
        if isinstance(file, str) and file and isinstance(field, str) and field:
            by_file.setdefault(file, set()).add(field)

    for fname, field_names in recorded_inventory(events).items():
        for name in field_names:
            feed(fname, name)
    if inventory is not None:
        for fname, field_names in inventory.files.items():
            for name in field_names:
                feed(fname, name)
    for oid, payload in observations.items():
        if is_data_observation(oid, observations):
            feed(payload.get("file"), payload.get("field"))
    return by_file


def recorded_inventory(events: list[LedgerEvent]) -> dict[str, list[str]]:
    """The export inventory recorded in a ledger: the union of its
    ``inventory`` events, each ``{"files": {FILE: [FIELD, ...]}}`` as
    the profiler wrote it (``Inventory.from_profile_report``). A
    malformed payload, file or field contributes nothing rather than
    raising, so one bad event cannot stop spec generation."""
    out: dict[str, set[str]] = {}
    for e in events:
        if e.type != "inventory":
            continue
        files = e.payload.get("files")
        if not isinstance(files, dict):
            continue
        for fname, fields in files.items():
            if not isinstance(fname, str) or not fname \
                    or not isinstance(fields, list):
                continue
            names = {f for f in fields if isinstance(f, str) and f}
            if names:
                out.setdefault(fname, set()).update(names)
    return {f: sorted(v) for f, v in sorted(out.items())}


def _valid_key_field(token: Any, known_by_file: dict[str, set[str]]) -> bool:
    if not isinstance(token, str) or not token:
        return False
    for part in token.split("+"):
        file, dot, field = part.rpartition(".")
        if not dot or not file or not field:
            return False
        fields = known_by_file.get(file)
        if fields is None or field not in fields:
            return False
    return True


def _valid_keying_story(value: Any,
                        known_by_file: dict[str, set[str]] | None = None) -> dict[str, Any] | None:
    """The keying story as a structured value, or None if it is not one.

    A keying story states which fields key a chart, whether a master
    index exists, and whether registration creates true duplicate charts
    — a dict whose only keys are ``key_fields`` (a non-empty list of
    field-reference tokens validated as above) and the optional
    booleans ``master_index`` and ``true_duplicates``. Field order is not
    meaningful: the returned story carries the fields de-duplicated and
    sorted, so the same fields in a different order are the same story.
    Anything else, above all a free-text string, is not a keying fact and
    cannot enter the spec as one."""
    if not isinstance(value, dict):
        return None
    if not set(value) <= {"key_fields", "master_index", "true_duplicates"}:
        return None
    fields = value.get("key_fields")
    if not isinstance(fields, list) or not fields:
        return None
    if any(not _valid_key_field(f, known_by_file or {}) for f in fields):
        return None
    for flag in ("master_index", "true_duplicates"):
        if flag in value and not isinstance(value[flag], bool):
            return None
    out: dict[str, Any] = {"key_fields": sorted(set(fields))}
    for flag in ("master_index", "true_duplicates"):
        if flag in value:
            out[flag] = value[flag]
    return out


def _field_subject_binding(subject: str) -> tuple[str, str] | None:
    """The (file, field) a ``field:`` subject names, parsed from the
    subject itself. Non-field subjects have no intrinsic binding: theirs
    is the (subject, predicate)-level binding recorded on the store
    (``ClaimStore.bindings``), from a ledger ``binding`` event. No
    binding, no confirmation. (A recorded binding for a ``field:``
    subject is refused at the store boundary, so this parse can never
    be shadowed by one.)"""
    if subject.startswith("field:"):
        rest = subject[len("field:"):]
        if "." in rest:
            file, field = rest.rsplit(".", 1)
            return file, field
    return None


def _conservative_kind(src: str) -> str:
    """The kind a source earns with no profiler data behind it: a ledger
    answer is an analyst; an estate document (dictionary, layouts,
    interface notes) is dictionary evidence; anything else is an analyst
    assertion. A source string that says "profiler" is a label, not
    evidence, and earns nothing here."""
    if src.startswith("ledger:"):
        return "analyst"
    low = src.lower()
    if any(mark in low for mark in ("dictionary", "datadict", "estate",
                                    "layouts", "interface notes")):
        return "dictionary"
    return "analyst"


def _claim_kind(claim: Claim, observations: dict[str, dict[str, Any]]) -> str:
    """The provenance kind of one claim, from its structured provenance
    when recorded, else from a conservative reading of its source: an exact
    data-observation source is profiler-data, a ledger answer is an
    analyst, an estate document (dictionary, layouts, interface notes) is
    dictionary evidence. Free text merely *mentioning* an observation or
    the profiler earns nothing — a source string that says "profiler" is
    a label, not evidence. A self-declared ``profiler-data`` kind with no
    evidence tying it to any recorded observation is demoted the same
    way: the kind must be earned, not asserted."""
    src = claim.source or ""
    first = src.split()[0].rstrip("(:") if src.split() else ""
    if claim.source_kind:
        if claim.source_kind != "profiler-data":
            return claim.source_kind
        tied = any(is_data_observation(r, observations)
                   for r in claim.evidence_refs) \
            or is_data_observation(first, observations)
        if tied:
            return "profiler-data"
        # Demote: fall through to the conservative source reading below.
    elif is_data_observation(first, observations):
        return "profiler-data"
    return _conservative_kind(src)


def _evidence_confirmed(refs: Any, expected: tuple[str, str],
                        observations: dict[str, dict[str, Any]]) -> bool:
    return any(observation_confirms(r, expected, observations) for r in refs)


def _rule_provenance(store: ClaimStore, subject: str, predicate: str, value: Any,
                     observations: dict[str, dict[str, Any]]) -> tuple[str, bool, str | None]:
    """(kind, data_confirmed, ref) for a rule, derived from validated evidence.

    The kind is the kind of the claim that stated the winning value (the
    claim is what the rule asserts); when no claim states the resolved
    value (a resolution introduced it), the resolution's own kind decides.
    ``data_confirmed`` is kept separate from who claimed the value: an
    analyst's claim confirmed by a profiler observation is analyst-kind
    and data-confirmed.

    When several claims state the winning value, the kind is the FIRST
    such claim's, and confirmation may come from any of them: a
    dictionary claim recorded before a profiler claim of the same value
    yields kind ``dictionary`` and, if the profiler claim's bound
    observation confirms it, ``data_confirmed: true``. The kind says
    who first stated the fact; ``data_confirmed`` says whether data
    backs it. (The scorecard credits profiling for a data-confirmed
    dictionary rule, so the measurement is not lost.) An unearned
    ``profiler-data`` kind is still demoted when nothing confirms.
    """
    dispute = store.dispute(subject, predicate)
    winners = [c for c in store.get(subject, predicate)
               if values_match(subject, predicate, c.value, value)]
    kind: str | None = None
    confirmed = False
    winning_src = ""
    # The binding an observation must match to confirm this rule: parsed
    # from a ``field:`` subject, else the (subject, predicate)-level
    # binding recorded on the store. Claims and resolutions carry no
    # binding of their own. A recorded binding counts only when it is
    # itself backed by evidence: at least one of its recorded refs must
    # be a real observation of the bound (file, field) — a binding
    # asserted with empty or unrelated refs (the self-binding route
    # through a bare binding event) confirms nothing. A conflicted
    # binding already reads as None from the store.
    subject_binding = _field_subject_binding(subject)
    if subject_binding is None:
        recorded = store.binding_for(subject, predicate)
        if recorded is not None and _evidence_confirmed(
                store.binding_refs.get((subject, predicate), ()),
                recorded, observations):
            subject_binding = recorded
    if winners:
        kind = _claim_kind(winners[0], observations)
        winning_src = winners[0].source or ""
        if subject_binding is not None:
            for c in winners:
                refs = list(c.evidence_refs)
                if c.source and c.source.split():
                    refs.append(c.source.split()[0].rstrip("(:"))
                if _evidence_confirmed(refs, subject_binding, observations):
                    confirmed = True
                    break
    if dispute is not None and dispute.resolved:
        # Structured evidence refs only. The resolution's free-text source
        # is a label for humans: an OBS id mentioned there — including in
        # a sentence saying it does NOT support the resolution — confirms
        # nothing.
        refs = list(dispute.resolution_evidence_refs)
        if subject_binding is not None and _evidence_confirmed(
                refs, subject_binding, observations):
            confirmed = True
        if kind is None:
            winning_src = dispute.resolution_source or ""
            kind = dispute.resolution_source_kind or (
                "profiler-data" if confirmed else "analyst")
    if (subject, predicate) == ("identity", "keying_story") \
            and isinstance(value, dict) and any(
                k not in ("key_fields", "master_index") for k in value):
        # A keying story that records a fact beyond its key fields and
        # master index (``true_duplicates``: how registration behaves)
        # is never data-confirmed. A binding names one (file, field),
        # and no observation of a field measures that fact — whoever
        # cites the observation, claim or resolution, and whatever kind
        # the citing event declares. Counting it would let a copied
        # ACCT observation ref "confirm" the duplicate-charts fact.
        confirmed = False
    kind = kind or "analyst"
    if kind == "profiler-data" and not confirmed:
        # The meeting point of the claim and resolution routes: the
        # profiler-data kind is earned only by subject-bound data
        # confirmation. A claim tied to data about some other subject,
        # or a resolution merely declaring the kind, demotes to the
        # conservative reading of the winning source.
        kind = _conservative_kind(winning_src)
    return kind, confirmed, store.provenance(subject, predicate)


def _with_extra_claims(store: ClaimStore, extra: list[Claim]) -> ClaimStore:
    """A copy of ``store`` with additional claims folded in (the original
    store is left untouched, keeping generate_spec a pure function)."""
    new = ClaimStore()
    new.claims = list(store.claims)
    new.bindings = dict(store.bindings)
    new.binding_refs = dict(store.binding_refs)
    new.binding_conflicts = {k: list(v) for k, v in store.binding_conflicts.items()}
    new.flagged_bindings = list(store.flagged_bindings)
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
    if not isinstance(source, str) or \
            not re.fullmatch(r"[a-z][a-z0-9_]*", source):
        # The source name lands in the generated profile's docstring and
        # identifiers; a quote payload there would close the docstring
        # and promote text into code. Same rule as the reader name.
        raise ValueError(
            f"source name is not a permitted identifier: {source!r}")
    if profile_report is not None:
        from .profiler import value_shape_claims
        extra = value_shape_claims(profile_report)
        if extra:
            store = _with_extra_claims(store, extra)
    observations = observation_payloads(events)
    known_fields = _known_fields(events, observations, inventory)
    rules: list[dict[str, Any]] = []
    overrides: list[dict[str, Any]] = []
    invalid_keying: Any = None
    # Subjects come from claims only. A resolution settles a dispute
    # among claims; a lone ``resolve`` event with nothing claimed
    # (ClaimStore.resolve creates the dispute anyway) is not a fact
    # anyone stated, so it never becomes a rule — otherwise one event
    # could emit a keying story, a crosswalk handling, or a layout,
    # with whatever provenance kind it declared for itself.
    # (The one exception is the merge-policy screen below: a lone
    # resolve on an identity merge predicate still reaches it, so the
    # override is recorded — it never becomes a rule either way.)
    keys = sorted({c.key() for c in store.claims} | {
        key for key, d in store.disputes.items()
        if key[0] == "identity" and key[1] != "keying_story" and d.resolved})
    n = 0
    for subject, predicate in keys:
        if subject == "identity" and predicate != "keying_story":
            # Merge policy is policy, not evidence — for ANY predicate that
            # expresses it, not only the one literally named merge_policy.
            # The resolved value counts too: resolving a merge dispute to
            # "auto_merge_all" is overridden and flagged exactly like
            # claiming it.
            claimed = [c.value for c in store.get(subject, predicate)]
            d = store.dispute(subject, predicate)
            if d is not None and d.resolved and d.resolved_value is not None \
                    and d.resolved_value not in claimed:
                claimed.append(d.resolved_value)
            if any(v != "route_to_reconciliation" for v in claimed):
                overrides.append({"subject": subject, "predicate": predicate,
                                  "claimed_values": claimed,
                                  "policy": "route_to_reconciliation"})
            continue  # the policy rule below replaces any claim on this key
        value = store.resolved_value(subject, predicate)
        if value is None:
            continue  # unresolved / null-resolved dispute -> known unknown
        if subject == "identity" and predicate == "keying_story":
            structured = _valid_keying_story(value, known_fields)
            if structured is None:
                # Not a structured keying fact — free text, or a malformed
                # structure — so it could carry an instruction no screen
                # has vetted. It is overridden by policy and flagged here,
                # exactly like a merge claim under any other predicate, and
                # the subject surfaces as a known unknown below instead of
                # entering the spec as a rule.
                overrides.append({"subject": subject, "predicate": predicate,
                                  "claimed_values": [value],
                                  "policy": "route_to_reconciliation"})
                invalid_keying = value
                continue
            value = structured
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
    if invalid_keying is not None:
        add_unknown("identity", "keying_story",
                    claimed_values=[invalid_keying],
                    disposition="runtime_question",
                    note="the keying story on record is not a structured "
                         "value (key fields, no action verb), so it is "
                         "flagged in policy_overrides and the keying "
                         "question goes to the runtime instead")
    known_unknowns.append({
        "subject": "identity", "predicate": "merge_decisions",
        "disposition": "runtime_question",
        "note": "Every proposed identity merge is decided by a human in "
                "reconciliation; the spec contains no auto-merge rule.",
    })

    reader_name = store.resolved_value("profile", "reader") or "fixed_width"
    if not isinstance(reader_name, str) or \
            not re.fullmatch(r"[a-z][a-z0-9_]*", reader_name):
        # The reader name is claim-derived text that ends up in the
        # generated profile; anything that is not a plain identifier is
        # rejected here rather than rendered.
        raise ValueError(
            f"reader name from claims is not a permitted identifier: "
            f"{reader_name!r}")
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


def _comment_text(text: str) -> str:
    """Flatten claim-derived text for a comment or docstring line in
    generated code. Control characters become visible escapes, so a
    newline inside a claim value or citation can never terminate the
    comment and promote data into an executable statement."""
    return (text.replace("\\", "\\\\").replace("\r", "\\r")
                .replace("\n", "\\n").replace("\t", "\\t"))


def _render_profile(source: str, rules: list[dict[str, Any]],
                    known_unknowns: list[dict[str, Any]],
                    reader_name: str = "fixed_width") -> str:
    by_const: dict[str, dict[str, Any]] = {}
    for rule in rules:
        const = PROFILE_CONSTANTS.get((rule["subject"], rule["predicate"]))
        if const:
            by_const[const] = rule
    lines = [
        f'"""GENERATED profile for {_comment_text(source)} by the Socratic import builder.',
        "",
        "Artifact of record: the declarative spec (spec.json) this was rendered",
        "from. Do not edit by hand; re-run the interview/spec generation.",
        '"""',
    ]
    if "CHARGE_CENTS_FROM" in by_const:
        lines.append("from datetime import date")
    lines.append("")
    lines.append(f"SOURCE_SYSTEM = {source!r}")
    lines.append(f"READER = {reader_name!r}")
    for const in sorted(by_const):
        rule = by_const[const]
        value = rule["value"]
        if const == "CHARGE_CENTS_FROM" and isinstance(value, str):
            y, m, d = (int(x) for x in value.split("-"))
            expr = f"date({y}, {m}, {d})"
        else:
            expr = repr(value)
        lines.append(f"# provenance: {_comment_text(rule['provenance']['kind'])}"
                     f" — {_comment_text(rule['provenance']['ref'])}"
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
