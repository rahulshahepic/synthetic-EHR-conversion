"""Mapping framework: fidelity annotations, reconciliation decisions, reference checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..runs import store as S
from ..terminology import TERMS, Terminology

FIDELITY_SCORE = {
    "exact": 1.0, "transformed": 1.0, "standardized": 1.0, "inferred": 0.8,
    "degraded": 0.5, "defaulted": 0.3, "dropped": 0.0,
}
LOSSY = {"inferred", "degraded", "defaulted", "dropped"}


@dataclass
class Annotation:
    field: str
    klass: str
    weight: float = 1.0
    note: str | None = None
    original: Any = None


@dataclass
class Outcome:
    status: str  # ok | held | blocked | dropped | superseded
    payload: dict[str, Any] | None = None
    note: str | None = None


class MapContext:
    """Per-record context handed to mappers."""

    def __init__(self, store: S.RunStore, run_id: str, rtype: str, rec: dict[str, Any], profile: Any,
                 terms: Terminology = TERMS):
        self.store, self.run_id, self.rtype, self.rec = store, run_id, rtype, rec
        self.key = rec["source_key"]
        self.seq: int | None = rec.get("seq")
        self.src: dict[str, Any] = rec["source"]
        self.profile = profile
        self.terms = terms
        self.annotations: list[Annotation] = []
        self.held_by: str | None = None
        self.blocked_by: str | None = None
        self.superseded_by: str | None = None
        # Mappers word prompts and notes for the hand-written Halcyon control; a generated profile
        # names its own source system so its questions don't talk about the wrong EHR.
        self.source_name: str = getattr(profile, "SOURCE_NAME", "Halcyon")

    # ------------------------------------------------------------ fidelity
    def note(self, field_: str, klass: str, weight: float = 1.0, note: str | None = None, original: Any = None) -> None:
        assert klass in FIDELITY_SCORE, klass
        if note and self.source_name != "Halcyon":
            note = note.replace("Halcyon", self.source_name)
        self.annotations.append(Annotation(field_, klass, weight, note, original))

    def fidelity(self) -> float:
        total = sum(a.weight for a in self.annotations)
        if not total:
            return 1.0
        return round(sum(FIDELITY_SCORE[a.klass] * a.weight for a in self.annotations) / total, 4)

    def losses(self) -> list[dict[str, Any]]:
        return [{"field": a.field, "klass": a.klass, "original": a.original, "note": a.note}
                for a in self.annotations if a.klass in LOSSY]

    # ------------------------------------------------------------ reconciliation
    def decide(self, kind: str, match_key: str, prompt: str, options: list[dict[str, Any]], *, blocking: bool,
               default: str | None = None, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Return the decision for (kind, match_key): a rule if one exists, else the default for
        non-blocking questions, else None (record must be held). Always files/links the question."""
        rule = self.store.rule(self.run_id, kind, match_key)
        if rule is not None:
            return rule
        if self.source_name != "Halcyon":
            prompt = prompt.replace("Halcyon", self.source_name)
        q = self.store.upsert_question(self.run_id, kind, match_key, prompt, options, blocking, context or {}, default)
        if q["status"] == "answered" and q["answer"]:
            return q["answer"]
        self.store.link_question(q["id"], self.rtype, self.key, used_default=not blocking)
        if blocking:
            self.held_by = q["id"]
            return None
        return {"option": default, "defaulted": True}

    # ------------------------------------------------------------ references
    def resolve_key(self, rtype: str, key: str) -> tuple[str, str | None]:
        """Follow supersession; return (key, status)."""
        seen = set()
        while key not in seen:
            seen.add(key)
            st = self.store.status_of(self.run_id, rtype, key)
            if st == S.SUPERSEDED:
                nxt = self.store.xget(self.run_id, "superseded", f"{rtype}/{key}")
                if nxt:
                    key = nxt
                    continue
            return key, st
        return key, None

    def require(self, rtype: str, key: str | None) -> dict[str, str] | None:
        """Reference a record that must be loaded first; otherwise block this record on it."""
        if not key:
            return None
        key, st = self.resolve_key(rtype, key)
        if st == S.LOADED:
            return {"sourceKey": f"{rtype}/{key}"}
        if self.blocked_by is None:
            self.blocked_by = f"{rtype}/{key}"
        return None

    def optional(self, rtype: str, key: str | None, field_: str) -> dict[str, str] | None:
        if not key:
            return None
        key2, st = self.resolve_key(rtype, key)
        if st == S.LOADED:
            return {"sourceKey": f"{rtype}/{key2}"}
        if st in (S.PENDING, S.HELD, S.BLOCKED):
            # the referenced record may still load (e.g. waiting on a question): wait rather than lose the link forever
            if self.blocked_by is None:
                self.blocked_by = f"{rtype}/{key2}"
            return None
        self.note(field_, "dropped", 0.5, f"referenced {rtype} {key} not available ({st or 'missing'})", key)
        return None

    def patient(self, pat_id: str) -> dict[str, str] | None:
        pkey = self.store.xget(self.run_id, "pat", pat_id)
        if pkey is None:
            self.blocked_by = self.blocked_by or f"Patient/?{pat_id}"
            return None
        return self.require("Patient", pkey)

    def patient_key(self, pat_id: str) -> str | None:
        pkey = self.store.xget(self.run_id, "pat", pat_id)
        return self.resolve_key("Patient", pkey)[0] if pkey else None

    def dedupe(self, scope: str, norm_key: str) -> bool:
        """True if an equivalent record (same scope + normalized key) was already claimed by another record."""
        xk = f"{self.rtype}:{scope}:{norm_key}"
        owner = self.store.xget(self.run_id, "dedupe", xk)
        if owner and owner != self.key and self.store.status_of(self.run_id, self.rtype, owner) not in (S.REJECTED, S.DROPPED, None):
            self.superseded_by = owner
            self.note("record", "dropped", 0.0, f"duplicate of {owner}")
            return True
        # Earliest record wins, independent of when answers arrive: don't claim while an earlier record of this
        # type for the same patient is still held or blocked (it may turn out to be the same thing).
        if self.seq is not None:
            pat_ids = self.store.patient_pat_ids(self.run_id, scope) or [scope]  # scope: patient key, else raw PAT_ID
            earlier = self.store.earliest_unresolved(self.run_id, self.rtype, pat_ids, self.seq)
            if earlier and earlier != self.key:
                self.blocked_by = self.blocked_by or f"{self.rtype}/{earlier}"
                return False
        self.store.xset(self.run_id, "dedupe", xk, self.key)
        return False


Mapper = Callable[[MapContext], dict[str, Any] | None]
MAPPERS: dict[str, Mapper] = {}


def mapper(rtype: str) -> Callable[[Mapper], Mapper]:
    def deco(fn: Mapper) -> Mapper:
        MAPPERS[rtype] = fn
        return fn
    return deco


def run_mapper(ctx: MapContext) -> Outcome:
    if ctx.src.get("_retire"):
        from .retire import map_source_deleted
        payload = map_source_deleted(ctx)
    elif ctx.src.get("_excluded"):
        # The source spec excludes this row (e.g. a cancelled result): dropped, with a loss-ledger reason.
        ctx.note("record", "dropped", 1.0, ctx.src["_excluded"])
        payload = None
    else:
        payload = MAPPERS[ctx.rtype](ctx)
        for n in ctx.src.get("_canonical_notes") or []:
            # A value the source spec derived rather than read (see interview/canonical.py).
            ctx.note(n["field"], n.get("klass", "inferred"), float(n.get("weight", 1.0)), n.get("note"), n.get("original"))
    if ctx.superseded_by:
        return Outcome("superseded", note=f"duplicate of {ctx.superseded_by}")
    if ctx.held_by:
        return Outcome("held", note=f"awaiting answer to {ctx.held_by}")
    if ctx.blocked_by:
        return Outcome("blocked", note=f"waiting for {ctx.blocked_by}")
    if payload is None:
        return Outcome("dropped", note=next((a.note for a in reversed(ctx.annotations) if a.klass == "dropped"), "dropped by policy"))
    return Outcome("ok", payload)
