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
from dataclasses import dataclass, field
from typing import Any


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


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
            if _canon(c.value) not in {_canon(v) for v in seen}:
                seen.append(c.value)
        return seen


class ClaimStore:
    def __init__(self) -> None:
        self.claims: list[Claim] = []
        self.disputes: dict[tuple[str, str], Dispute] = {}

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
            known = {_canon(c.value) for c in d.claims} | {_canon(d.resolved_value)}
            if _canon(claim.value) not in known:
                d.resolved_value = None
                d.resolution_source = None
                d.resolution_claimed_by = ""
                d.resolution_source_kind = ""
                d.resolution_evidence_refs = ()
        self.claims.append(claim)
        existing = [c for c in self.claims if c.key() == key]
        distinct = {_canon(c.value) for c in existing}
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
                if _canon(c.value) == _canon(d.resolved_value):
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
        ``resolve`` events resolve disputes. Deterministic in event order."""
        store = cls()
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
        }
