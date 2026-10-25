"""The claim store: everything the Socratic builder believes, with provenance.

A claim is ``(subject, predicate, value, source, confidence)``. Sources are
dictionary references (``DATADICT.TXT v4.1: REG.DOB``), profiler observation
ids (``OBS-0007``), or ledger events (``ledger:E000017``). A source dictionary
is ingested as claims at its stated version, so when the dictionary is stale
the staleness shows up as disputes against observations and analyst answers
instead of being silently believed.

Two claims on the same ``(subject, predicate)`` with different values form a
:class:`Dispute` — a first-class object with a resolution state, never an
overwrite. Spec generation (specgen.py) may only consume resolved values:
the single undisputed value, or a dispute's recorded resolution.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


def _canon(value: Any, *, keying_story: bool = False) -> str:
    if keying_story and isinstance(value, dict) \
            and isinstance(value.get("key_fields"), list) \
            and all(isinstance(f, str) for f in value["key_fields"]):
        # A keying story's field order is not meaningful: the same fields
        # in a different order are the same story, not a dispute. This is
        # scoped to the keying story ONLY: other values that happen to
        # carry a ``key_fields`` list (a layout binding's ordered
        # composite key, say) are ordered on purpose, and reordering
        # them in the generic canonicalizer would erase real disputes.
        value = {**value, "key_fields": sorted(set(value["key_fields"]))}
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _canon_for(subject: str, predicate: str, value: Any) -> str:
    return _canon(value, keying_story=(subject, predicate) == ("identity", "keying_story"))


def _keying_core(value: Any) -> tuple[tuple[str, ...], Any] | None:
    """The identity-bearing core of a keying story: its key fields
    (order-insensitive) and its master-index flag. A resolution may add
    further recorded facts on top of the winning claim's story (the
    Delphi resolution adds ``true_duplicates``); the claim that stated
    the core is still the story's provenance."""
    if not isinstance(value, dict):
        return None
    fields = value.get("key_fields")
    if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
        return None
    return (tuple(sorted(set(fields))), value.get("master_index"))


def values_match(subject: str, predicate: str, a: Any, b: Any) -> bool:
    """Whether two values on (subject, predicate) are the same value.
    For the keying story, a value also matches a claim that stated its
    core (same key fields, same master-index flag) even when a
    resolution added further facts (e.g. ``true_duplicates``) on top."""
    if _canon_for(subject, predicate, a) == _canon_for(subject, predicate, b):
        return True
    if (subject, predicate) == ("identity", "keying_story"):
        core_a, core_b = _keying_core(a), _keying_core(b)
        return core_a is not None and core_a == core_b
    return False


def validate_binding(value: Any) -> tuple[str, str]:
    """A subject-to-field binding is exactly two non-empty strings:
    ``(file, field)``. Anything else — a bare string, a 1- or 3-element
    sequence, a non-string element — is rejected with a clear error.

    This is the one place bindings are validated. A binding is recorded
    once per (subject, predicate) (a ledger ``binding`` event, or
    ``ClaimStore.bind``), never carried on an individual claim or
    resolution, so no claim can bind itself to whatever observation it
    happens to cite."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(
            f"binding must be a (file, field) pair, got {value!r}")
    if len(value) != 2:
        raise ValueError(
            f"binding must have exactly two elements (file, field), "
            f"got {value!r}")
    file, field = value
    if not isinstance(file, str) or not isinstance(field, str) \
            or not file.strip() or not field.strip():
        raise ValueError(
            f"binding elements must be non-empty strings, got {value!r}")
    return file, field


@dataclass(frozen=True)
class Claim:
    subject: str
    predicate: str
    value: Any
    source: str
    confidence: float = 1.0
    # Structured provenance, recorded explicitly by the ledger event (or the
    # caller) instead of being guessed from the free-text ``source`` string.
    # ``source_kind`` is one of "analyst", "profiler-data", "dictionary",
    # "document". ``evidence_refs`` are references the spec generator can
    # validate: a profiler observation id ("OBS-0007"), a ledger event id
    # ("E000017"), or an analyst id.
    source_kind: str = ""
    evidence_refs: tuple[str, ...] = ()
    # Deliberately NO subject-to-field binding here: a binding belongs to
    # the subject, recorded once on the store (see ClaimStore.bindings).
    # A per-claim binding lets any claim declare itself confirmed by
    # whatever observation it cites.

    def key(self) -> tuple[str, str]:
        return (self.subject, self.predicate)


@dataclass
class Dispute:
    subject: str
    predicate: str
    claims: list[Claim] = field(default_factory=list)
    resolved_value: Any = None
    resolution_source: str | None = None
    # Structured resolution provenance: who/what stated the resolved value
    # (``resolution_claimed_by``), the kind of that evidence, and the
    # references specgen validates for data confirmation.
    resolution_claimed_by: str = ""
    resolution_source_kind: str = ""
    resolution_evidence_refs: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.resolution_source is not None

    @property
    def values(self) -> list[Any]:
        seen: list[Any] = []
        for c in self.claims:
            if _canon_for(self.subject, self.predicate, c.value) not in \
                    {_canon_for(self.subject, self.predicate, v) for v in seen}:
                seen.append(c.value)
        return seen


class ClaimStore:
    def __init__(self) -> None:
        self.claims: list[Claim] = []
        self.disputes: dict[tuple[str, str], Dispute] = {}
        # Subject-to-field bindings, keyed by (subject, predicate): the
        # (file, field) a profiler observation must describe to
        # data-confirm a claim on that one (subject, predicate). Keying
        # by subject alone would let one predicate's observation
        # "confirm" every other predicate on the subject. Recorded once
        # per (subject, predicate) — in a ledger, as a ``binding`` event
        # with its own evidence refs — never per claim.
        self.bindings: dict[tuple[str, str], tuple[str, str]] = {}
        self.binding_refs: dict[tuple[str, str], tuple[str, ...]] = {}
        # A second, different binding for an already-bound
        # (subject, predicate) is a conflict, not an overwrite: the
        # first binding stays, the conflicting one is recorded here,
        # and a conflicted key earns no data confirmation.
        self.binding_conflicts: dict[tuple[str, str], list[tuple[str, str]]] = {}
        # Binding events skipped during ledger replay (malformed shape,
        # no predicate, a ``field:`` subject, or no cited observation
        # describing the bound field), with the reason for each.
        self.flagged_bindings: list[dict[str, Any]] = []

    def add(self, claim: Claim) -> Dispute | None:
        """Add a claim; returns the Dispute it created or joined, else None.

        A claim carrying a genuinely new value — one that was neither among
        the claims a resolved dispute already held nor the resolved value
        itself — REOPENS that dispute: the resolution no longer stands.
        A corroborating claim (a value the dispute already knew) leaves the
        resolution untouched.
        """
        key = claim.key()
        d = self.disputes.get(key)
        if d is not None and d.resolved:
            known = {_canon_for(key[0], key[1], c.value) for c in d.claims} \
                | {_canon_for(key[0], key[1], d.resolved_value)}
            if _canon_for(key[0], key[1], claim.value) not in known:
                d.resolved_value = None
                d.resolution_source = None
                d.resolution_claimed_by = ""
                d.resolution_source_kind = ""
                d.resolution_evidence_refs = ()
        self.claims.append(claim)
        existing = [c for c in self.claims if c.key() == key]
        distinct = {_canon_for(key[0], key[1], c.value) for c in existing}
        if len(distinct) > 1:
            if d is None:
                d = Dispute(subject=key[0], predicate=key[1])
                self.disputes[key] = d
            d.claims = existing
            return d
        return self.disputes.get(key)

    def get(self, subject: str, predicate: str) -> list[Claim]:
        return [c for c in self.claims if c.key() == (subject, predicate)]

    def dispute(self, subject: str, predicate: str) -> Dispute | None:
        return self.disputes.get((subject, predicate))

    def resolve(self, subject: str, predicate: str, value: Any, source: str,
                claimed_by: str = "", source_kind: str = "",
                evidence_refs: tuple[str, ...] = ()) -> Dispute:
        """Record a resolution for a dispute (the value need not be one of the
        claimed values, but the source must say why: an observation id, a
        ledger event, a named analyst).

        The resolution may legitimately be ``None`` — "the field is absent" —
        in which case the dispute counts as resolved for provenance purposes
        but spec generation still surfaces it as a known unknown rather than
        silently dropping the subject (see specgen).
        """
        key = (subject, predicate)
        d = self.disputes.get(key)
        if d is None:
            d = Dispute(subject=subject, predicate=predicate,
                        claims=self.get(subject, predicate))
            self.disputes[key] = d
        d.resolved_value = value
        d.resolution_source = source
        d.resolution_claimed_by = claimed_by
        d.resolution_source_kind = source_kind
        d.resolution_evidence_refs = tuple(evidence_refs)
        return d

    # -- subject bindings ----------------------------------------------------
    def bind(self, subject: str, binding: Any,
             evidence_refs: tuple[str, ...] = (), predicate: str = "") -> None:
        """Record the (subject, predicate)-to-field binding: the (file,
        field) a profiler observation must describe to data-confirm a
        claim on this (subject, predicate). The binding's shape is
        validated here, at the one boundary (``validate_binding``); a
        malformed binding raises and records nothing.

        A binding needs a predicate: keyed by subject alone, one
        predicate's observation would confirm every predicate on the
        subject. A ``field:`` subject names its own (file, field) in the
        subject itself, so recording a binding for one is rejected —
        it could only ever agree silently or be silently ignored.

        A second binding for the same (subject, predicate) with the
        SAME value merges its evidence refs. A DIFFERENT value is a
        conflict, not an overwrite: the first binding stays, the
        conflicting one is recorded in ``binding_conflicts``, and the
        conflicted key earns no data confirmation (``binding_for``
        returns None for it)."""
        if not isinstance(predicate, str) or not predicate:
            raise ValueError(
                "a binding must name the predicate it binds: bindings "
                "are keyed by (subject, predicate), never by subject alone")
        if subject.startswith("field:"):
            raise ValueError(
                f"a field: subject names its own binding in the subject "
                f"itself; refusing a recorded binding for {subject!r}")
        parsed = validate_binding(binding)
        key = (subject, predicate)
        existing = self.bindings.get(key)
        if existing is not None and existing != parsed:
            self.binding_conflicts.setdefault(key, []).append(parsed)
            return
        self.bindings[key] = parsed
        merged = list(self.binding_refs.get(key, ()))
        for ref in evidence_refs:
            if ref not in merged:
                merged.append(ref)
        self.binding_refs[key] = tuple(merged)

    def binding_for(self, subject: str, predicate: str = "") -> tuple[str, str] | None:
        key = (subject, predicate)
        if key in self.binding_conflicts:
            return None
        return self.bindings.get(key)

    def resolved_value(self, subject: str, predicate: str, default: Any = None) -> Any:
        """The value spec generation may use: a dispute's resolution, else the
        single undisputed claimed value, else ``default``."""
        d = self.disputes.get((subject, predicate))
        if d is not None:
            return d.resolved_value if d.resolved else default
        vals = self.get(subject, predicate)
        if not vals:
            return default
        return vals[0].value

    def provenance(self, subject: str, predicate: str) -> str | None:
        """Best provenance string for a resolved value, for spec comments."""
        d = self.disputes.get((subject, predicate))
        if d is not None and d.resolved:
            for c in d.claims:
                if values_match(subject, predicate, c.value, d.resolved_value):
                    return f"{c.source}; dispute resolved via {d.resolution_source}"
            return f"dispute resolved via {d.resolution_source}"
        vals = self.get(subject, predicate)
        return vals[0].source if vals else None

    def unresolved_disputes(self) -> list[Dispute]:
        return [d for d in self.disputes.values() if not d.resolved]

    def null_resolved_disputes(self) -> list[Dispute]:
        """Disputes resolved to ``None`` ("the field is absent"). They are
        resolved, so they are not unresolved — but the subject must still
        surface as a known unknown rather than vanishing from the spec."""
        return [d for d in self.disputes.values()
                if d.resolved and d.resolved_value is None]

    # -- dictionary ingest -------------------------------------------------
    def ingest_rows(self, rows: list[dict[str, Any]], source: str,
                    confidence: float = 0.8) -> int:
        """Ingest dictionary rows of the form
        ``{"subject": ..., "predicate": ..., "value": ...}`` as claims whose
        source is the dictionary artifact. Returns the number ingested."""
        n = 0
        for row in rows:
            self.add(Claim(subject=row["subject"], predicate=row["predicate"],
                           value=row["value"], source=source,
                           confidence=row.get("confidence", confidence),
                           source_kind="dictionary"))
            n += 1
        return n

    # -- ledger replay -----------------------------------------------------
    @classmethod
    def from_ledger(cls, events: list) -> "ClaimStore":
        """Rebuild a store from a ledger: ``claim`` events assert claims,
        ``resolve`` events resolve disputes, ``binding`` events record
        (subject, predicate)-to-field bindings. Deterministic in event
        order.

        A binding event is evidence, not an instruction: it is recorded
        only when at least one of its cited refs is a real profiler data
        observation (an ``OBS-<digits>`` event with stats) describing
        exactly the bound (file, field). A bad binding event — malformed
        shape, missing subject or predicate, a ``field:`` subject, or
        no such observation behind it — never aborts the replay and
        never binds anything: it is skipped and recorded in
        ``flagged_bindings`` with the reason, so one bad event cannot
        take down spec generation, the scorecard, and the diff for the
        whole source. (Direct ``bind()`` callers still get the raise:
        they are code, not recorded evidence.)"""
        store = cls()
        observations: dict[str, dict[str, Any]] = {}
        for e in events:
            if e.type == "observation":
                oid = e.payload.get("obs_id")
                if oid:
                    observations[oid] = e.payload

        def binding_evidence_ok(refs: tuple[str, ...],
                                parsed: tuple[str, str]) -> bool:
            for ref in refs:
                if not isinstance(ref, str) or not re.match(r"^OBS-\d+$", ref):
                    continue
                payload = observations.get(ref, {})
                if not payload.get("stats"):
                    continue
                actual = (str(payload.get("file", "")), str(payload.get("field", "")))
                if (actual[0].lower(), actual[1].lower()) == \
                        (parsed[0].lower(), parsed[1].lower()):
                    return True
            return False

        for e in events:
            p = e.payload
            if e.type == "claim":
                store.add(Claim(subject=p["subject"], predicate=p["predicate"],
                                value=p.get("value"), source=p["source"],
                                confidence=p.get("confidence", 1.0),
                                source_kind=p.get("source_kind", ""),
                                evidence_refs=tuple(p.get("evidence_refs", ()))))
            elif e.type == "resolve":
                store.resolve(p["subject"], p["predicate"], p.get("value"), p["source"],
                              claimed_by=p.get("claimed_by", ""),
                              source_kind=p.get("source_kind", ""),
                              evidence_refs=tuple(p.get("evidence_refs", ())))
            elif e.type == "binding":
                # A binding event records the (subject, predicate)'s
                # (file, field) once, with its own evidence refs. The
                # event is checked here (shape, subject, predicate,
                # evidence) and SKIPPED + flagged when bad — see the
                # docstring. bind() itself still raises for direct
                # callers.
                subject = p.get("subject")
                predicate = p.get("predicate")
                refs_raw = p.get("evidence_refs", ())
                refs = tuple(refs_raw) if isinstance(refs_raw, (list, tuple)) else ()
                reason: str | None = None
                parsed: tuple[str, str] | None = None
                try:
                    parsed = validate_binding(p.get("binding"))
                except ValueError as exc:
                    reason = str(exc)
                if reason is None:
                    if not isinstance(subject, str) or not subject:
                        reason = "binding event has no subject"
                    elif not isinstance(predicate, str) or not predicate:
                        reason = "binding event has no predicate"
                    elif subject.startswith("field:"):
                        reason = ("a field: subject names its own binding "
                                  "in the subject itself")
                    elif parsed is None or not binding_evidence_ok(refs, parsed):
                        reason = ("no cited observation describes the bound "
                                  "(file, field)")
                if reason is not None:
                    store.flagged_bindings.append({
                        "event": e.id, "subject": subject,
                        "predicate": predicate, "binding": p.get("binding"),
                        "evidence_refs": list(refs), "reason": reason})
                    continue
                store.bind(subject, parsed, evidence_refs=refs,
                           predicate=predicate)
        return store

    def to_json(self) -> dict[str, Any]:
        def claim_json(c: Claim) -> dict[str, Any]:
            out: dict[str, Any] = {"subject": c.subject, "predicate": c.predicate,
                                   "value": c.value, "source": c.source,
                                   "confidence": c.confidence}
            if c.source_kind:
                out["source_kind"] = c.source_kind
            if c.evidence_refs:
                out["evidence_refs"] = list(c.evidence_refs)
            return out

        def dispute_json(d: Dispute) -> dict[str, Any]:
            out: dict[str, Any] = {"subject": d.subject, "predicate": d.predicate,
                                   "values": d.values, "resolved": d.resolved,
                                   "resolved_value": d.resolved_value,
                                   "resolution_source": d.resolution_source}
            if d.resolution_claimed_by:
                out["resolution_claimed_by"] = d.resolution_claimed_by
            if d.resolution_source_kind:
                out["resolution_source_kind"] = d.resolution_source_kind
            if d.resolution_evidence_refs:
                out["resolution_evidence_refs"] = list(d.resolution_evidence_refs)
            return out

        return {
            "claims": [claim_json(c) for c in self.claims],
            "disputes": [dispute_json(d) for d in sorted(
                self.disputes.values(), key=lambda d: (d.subject, d.predicate))],
            "bindings": [{"subject": s, "predicate": pred, "binding": list(b),
                          "evidence_refs": list(self.binding_refs.get((s, pred), ()))}
                         for (s, pred), b in sorted(self.bindings.items())],
            "binding_conflicts": [
                {"subject": s, "predicate": pred,
                 "kept": list(self.bindings[(s, pred)]),
                 "rejected": [list(b) for b in rejected]}
                for (s, pred), rejected in sorted(self.binding_conflicts.items())],
            "flagged_bindings": list(self.flagged_bindings),
        }
