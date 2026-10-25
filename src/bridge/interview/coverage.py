"""The coverage checklist: what an import spec must establish, derived from
the spec schema — not from anyone's memory of a particular source system.

For each file in the export inventory, the spec needs a layout binding. For
each field, a convention decision (type, and where relevant a date format, a
unit, or a code set) or an explicit pass-through-as-text decision. Identity
needs a keying story. Every code set needs a crosswalk or a documented gap.

An item is ``covered`` when the claim store holds an undisputed (or resolved)
claim for it, ``disputed`` when its claims conflict unresolved, and ``open``
when nobody has established anything yet. Open and disputed items at spec
time become the generated spec's known unknowns — never silent defaults.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .claims import ClaimStore


@dataclass(frozen=True)
class Inventory:
    """What the export contains, as the profiler/layout describes it."""
    files: dict[str, list[str]]          # file name -> field names
    code_sets: list[str]                 # named code sets needing crosswalks

    @classmethod
    def from_profile_report(cls, report: dict[str, Any], code_sets: list[str] | None = None) -> "Inventory":
        return cls(files={name: sorted(data["fields"]) for name, data in report["files"].items()},
                   code_sets=sorted(code_sets or []))


@dataclass(frozen=True)
class ChecklistItem:
    id: str
    subject: str
    predicate: str
    description: str
    status: str                          # covered | disputed | open
    evidence: str | None = None          # provenance of the covering claim

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "subject": self.subject, "predicate": self.predicate,
                "description": self.description, "status": self.status,
                "evidence": self.evidence}


def build_checklist(inventory: Inventory, store: ClaimStore) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []

    def status_for(subject: str, predicate: str,
                   alt_predicates: tuple[str, ...] = ()) -> tuple[str, str | None]:
        for pred in (predicate, *alt_predicates):
            d = store.dispute(subject, pred)
            if d is not None:
                if d.resolved:
                    return "covered", store.provenance(subject, pred)
                return "disputed", None
            if store.get(subject, pred):
                return "covered", store.provenance(subject, pred)
        return "open", None

    n = 0

    def add(subject: str, predicate: str, description: str,
            alt: tuple[str, ...] = ()) -> None:
        nonlocal n
        n += 1
        status, evidence = status_for(subject, predicate, alt)
        items.append(ChecklistItem(id=f"C{n:03d}", subject=subject, predicate=predicate,
                                   description=description, status=status, evidence=evidence))

    for fname in sorted(inventory.files):
        add(f"file:{fname}", "layout_binding", f"Layout binding for {fname}")
        for field in inventory.files[fname]:
            add(f"field:{fname}.{field}", "convention",
                f"Type/format convention for {fname}.{field}",
                alt=("pass_through_text",))
    add("identity", "keying_story",
        "How records for the same person are keyed and matched")
    for cs in inventory.code_sets:
        add(f"codeset:{cs}", "crosswalk", f"Crosswalk (or documented gap) for code set {cs}",
            alt=("documented_gap",))
    return items


def uncovered(items: list[ChecklistItem]) -> list[ChecklistItem]:
    return [i for i in items if i.status != "covered"]
