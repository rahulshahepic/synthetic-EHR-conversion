"""Crosswalk lookups backed by CSV files in terminology/data."""
from __future__ import annotations

import csv
from collections import defaultdict
from functools import cached_property
from pathlib import Path

DATA = Path(__file__).parent / "data"


def _rows(name: str) -> list[dict[str, str]]:
    path = DATA / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


class Terminology:
    @cached_property
    def icd9(self) -> dict[str, list[tuple[str, str]]]:
        out: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in _rows("icd9_icd10.csv"):
            out[r["icd9"]].append((r["icd10"], r["description"]))
        return dict(out)

    @cached_property
    def icd10_retired(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for r in _rows("icd10_retired.csv"):
            out[r["code"]].append(r["replacement"])
        return dict(out)

    @cached_property
    def local_dx(self) -> dict[str, tuple[str, str]]:
        return {r["local_code"]: (r["icd10"], r["description"]) for r in _rows("local_dx.csv")}

    @cached_property
    def allergens(self) -> dict[str, tuple[str, str, str]]:
        return {_norm(r["text"]): (r["system"], r["code"], r["display"]) for r in _rows("allergen.csv")}

    @cached_property
    def reactions(self) -> dict[str, tuple[str, str]]:
        return {_norm(r["text"]): (r["snomed"], r["display"]) for r in _rows("reaction.csv")}

    @cached_property
    def specialties(self) -> dict[str, str]:
        return {_norm(r["text"]): r["specialty"] for r in _rows("specialty.csv")}

    @cached_property
    def race(self) -> dict[str, tuple[str | None, str | None]]:
        return {_norm(r["text"]): (r["race"] or None, r["ethnicity"] or None) for r in _rows("race.csv")}

    @cached_property
    def visit_class(self) -> dict[str, str]:
        return {r["code"]: r["class"] for r in _rows("visit_class.csv")}

    @cached_property
    def labs(self) -> dict[str, tuple[str, str, str]]:
        return {r["local_code"]: (r["loinc"], r["ucum_unit"], r["display"]) for r in _rows("lab_loinc.csv")}

    @cached_property
    def formulary(self) -> dict[str, tuple[str, str]]:
        return {r["form_code"]: (r["rxnorm"], r["display"]) for r in _rows("formulary_rxnorm.csv")}

    @cached_property
    def vaccines(self) -> dict[str, tuple[str, str]]:
        return {r["local_code"]: (r["cvx"], r["display"]) for r in _rows("vaccine_cvx.csv")}

    @cached_property
    def note_types(self) -> dict[str, tuple[str, str]]:
        return {r["local_code"]: (r["loinc"], r["display"]) for r in _rows("note_type_loinc.csv")}

    @staticmethod
    def norm(text: str) -> str:
        return _norm(text)


TERMS = Terminology()
