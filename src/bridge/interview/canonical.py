"""Canonical staging: a generated spec's canonical binding turns source rows into the staged
records Bridge's mappers consume.

Bridge's mappers read one staged shape per resource type (the field names the hand-written
Halcyon reader stages: ``PAT_ID``, ``DOB`` as ``YYYYMMDD``, ``ADMIT_DT`` as ``YYYYMMDDHHMM``...).
A source the Socratic builder learned arrives in its own files and conventions. The interview
establishes, claim by claim, which source field plays which canonical role and how its values
read (date format, code values, placeholders, rows to exclude); the spec generator assembles
those into the reader binding's ``canonical`` section; this module applies it. It knows no
source system: everything source-specific arrives through the binding.

Field expressions (the binding's vocabulary):

- ``"FIELD"`` — the source field's value, stripped.
- ``{"const": v}`` — a constant.
- ``{"format": "{A},{B} {C}"}`` — source fields interpolated, whitespace collapsed at the ends.
- ``{"field": F, ...}`` with modifiers applied in order:
  ``null_values`` (values that mean "unknown" become blank), ``map`` (+ ``map_default``:
  ``"keep"`` keeps unmapped values, anything else replaces them), ``date``/``datetime``
  (a strptime format; output ``YYYYMMDD`` / ``YYYYMMDDHHMM``; unparseable values are kept
  raw so the mapper's own checks see them), ``icd_decimal`` (``{"system_field": F,
  "icd9": code}``: re-inserts the decimal point the source stripped), ``lookup``
  (``{"file": stem, "key": K, "value": V}``: the value of V in the reference row keyed by
  this value).

Rows matching a mapping's ``exclude`` (``{field: [values]}``) are staged with an
``_excluded`` reason, so the mapper drops them visibly (loss ledger), never silently.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..mapping import identity

Row = dict[str, str]


class DelimitedExport:
    """A header-row delimited export described by a reader binding's ``format`` section."""

    def __init__(self, path: str | Path, binding: dict[str, Any]):
        self.path = Path(path)
        self.binding = binding
        fmt = binding.get("format") or {}
        self.delimiter = fmt.get("delimiter")
        self.encoding = fmt.get("encoding", "utf-8")
        self.suffix = fmt.get("suffix", ".csv")
        if not self.delimiter:
            raise ValueError("delimited reader binding declares no delimiter")
        mp = self.path / "manifest.json"
        self.manifest: dict[str, Any] = json.loads(mp.read_text()) if mp.exists() else {}
        self._cache: dict[str, list[Row]] = {}

    def rows(self, stem: str) -> list[Row]:
        """Every row of a file, as {header: value}. A missing file, a short or long row, or a
        row count that disagrees with the manifest is a loud error."""
        if stem in self._cache:
            return self._cache[stem]
        fpath = self.path / f"{stem}{self.suffix}"
        if not fpath.exists():
            raise FileNotFoundError(f"bound file missing from export: {fpath}")
        lines = [ln for ln in fpath.read_bytes().decode(self.encoding).splitlines() if ln.strip()]
        if not lines:
            raise ValueError(f"{fpath.name}: no header row")
        header = [h.strip() for h in lines[0].split(self.delimiter)]
        out = []
        for n, line in enumerate(lines[1:], 2):
            cells = line.split(self.delimiter)
            if len(cells) != len(header):
                raise ValueError(f"{fpath.name} line {n}: {len(cells)} cells, header has {len(header)}")
            out.append({h: c.strip() for h, c in zip(header, cells)})
        expected = self.manifest.get("counts", {}).get(stem)
        if expected is not None and expected != len(out):
            raise ValueError(f"{fpath.name}: parsed {len(out)} rows but the manifest counts {expected}")
        self._cache[stem] = out
        return out


# ----------------------------------------------------------------------------- expressions
_FMT = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _icd_decimal(code: str, is_icd9: bool) -> str:
    if not code or "." in code:
        return code
    if is_icd9:
        cut = 4 if code.startswith("E") else 3
    else:
        cut = 3
    return code if len(code) <= cut else f"{code[:cut]}.{code[cut:]}"


class Evaluator:
    def __init__(self, export: DelimitedExport):
        self.export = export
        self._lookups: dict[tuple[str, str], dict[str, Row]] = {}

    def _lookup(self, spec: dict[str, str], value: str) -> str:
        idx_key = (spec["file"], spec["key"])
        if idx_key not in self._lookups:
            self._lookups[idx_key] = {r[spec["key"]]: r for r in self.export.rows(spec["file"])}
        return self._lookups[idx_key].get(value, {}).get(spec["value"], "")

    def value(self, expr: Any, row: Row) -> str:
        if isinstance(expr, str):
            return row.get(expr, "")
        if not isinstance(expr, dict):
            raise ValueError(f"bad field expression {expr!r}")
        if "const" in expr:
            return str(expr["const"])
        if "format" in expr:
            text = _FMT.sub(lambda m: row.get(m.group(1), ""), expr["format"])
            return re.sub(r"\s+", " ", text).strip(" ,")
        v = row.get(expr["field"], "")
        if v in expr.get("null_values", []):
            v = ""
        if "map" in expr and v:
            mapped = expr["map"].get(v)
            if mapped is not None:
                v = mapped
            elif expr.get("map_default", "keep") != "keep":
                v = expr["map_default"]
        for kind, out_fmt in (("date", "%Y%m%d"), ("datetime", "%Y%m%d%H%M")):
            if kind in expr and v:
                try:
                    v = datetime.strptime(v, expr[kind]).strftime(out_fmt)
                except ValueError:
                    pass  # keep raw: the mapper's own date checks reject and annotate it
        if "icd_decimal" in expr and v:
            spec = expr["icd_decimal"]
            v = _icd_decimal(v, row.get(spec["system_field"], "") == spec["icd9"])
        if "lookup" in expr and v:
            v = self._lookup(expr["lookup"], v)
        return v

    def record(self, mapping: dict[str, Any], row: Row) -> dict[str, str]:
        return {name: self.value(expr, row) for name, expr in mapping["fields"].items()}


def _excluded(mapping: dict[str, Any], row: Row) -> str | None:
    for fld, values in (mapping.get("exclude") or {}).items():
        if row.get(fld, "") in values:
            reason = (mapping.get("exclude_reason") or {}).get(row.get(fld, ""), "")
            return f"source {fld}={row.get(fld)} excluded by spec" + (f": {reason}" if reason else "")
    return None


# ----------------------------------------------------------------------------- staging
def stage_canonical(store: Any, run_id: str, export: DelimitedExport, profile: Any) -> dict[str, int]:
    canon = export.binding.get("canonical") or {}
    if not canon:
        raise ValueError("reader binding has no canonical section: nothing maps source rows to resource types")
    ev = Evaluator(export)
    counts: dict[str, int] = {}

    def lin(stem: str, key: Any) -> dict[str, Any]:
        return {"channel": "delimited", "table": stem, "id": key}

    def rows_of(mapping: dict[str, Any]) -> Iterator[tuple[Row, dict[str, str]]]:
        for row in export.rows(mapping["file"]):
            yield row, ev.record(mapping, row)

    # --- organizations and locations
    org = canon["Organization"]
    sites = [rec for _, rec in rows_of(org["sites"])]
    depts = [rec for _, rec in rows_of(org["departments"])]
    store.xset(run_id, "meta", "facilities", sorted(s["FAC_ID"] for s in sites))
    store.xset(run_id, "meta", "facility_names", {s["FAC_ID"]: s["FAC_NAME"] for s in sites})
    store.xset(run_id, "meta", "manifest_notes", export.manifest.get("notes", {}))
    orgs = [(profile.SYSTEM_ORG["key"], {"kind": "system", "name": profile.SYSTEM_ORG["name"]},
             {"channel": "profile", "note": "source has no system level; synthesized"})]
    for s in sites:
        orgs.append((f"SITE-{s['FAC_ID']}", {"kind": "site", **s}, lin(org["sites"]["file"], s["FAC_ID"])))
    locs = []
    for d in depts:
        key = f"{d['DEPT_ID']}@{d['FAC_ID']}"
        payload = {"kind": "department", **d, "SITE": d["FAC_ID"], "SHARED": False}
        orgs.append((f"DEPT-{key}", payload, lin(org["departments"]["file"], d["DEPT_ID"])))
        locs.append((f"LOC-{key}", payload, lin(org["departments"]["file"], d["DEPT_ID"])))
    counts["Organization"] = store.stage(run_id, "Organization", orgs)
    counts["Location"] = store.stage(run_id, "Location", locs)
    dept_fac = {d["DEPT_ID"]: d["FAC_ID"] for d in depts}

    for rtype in ("Practitioner", "Payer", "Plan"):
        m = canon.get(rtype)
        if m:
            counts[rtype] = store.stage(run_id, rtype, ((row[m["key"]], rec, lin(m["file"], row[m["key"]]))
                                                        for row, rec in rows_of(m)))

    # --- identity: every chart is a candidate; merges route per the profile's policy
    pm = canon["Patient"]
    pats = []
    for row, rec in rows_of(pm):
        if rec.get("PAT_ID") != row[pm["key"]]:
            raise ValueError("canonical Patient binding must map PAT_ID to the file's key field")
        pats.append(rec)
    pat_by_id = {p["PAT_ID"]: p for p in pats}
    auto_merge = getattr(profile, "MERGE_POLICY", None) != "route_to_reconciliation"
    clusters, review, reasons = identity.resolve(pats, [], auto_merge=auto_merge)
    root_of = {m: root for root, members in clusters.items() for m in members}
    am = canon.get("AllergyIntolerance")
    allergy_rows = [(row, rec) for row, rec in rows_of(am)] if am else []
    real_allergy_pats = {rec["PAT_ID"] for _, rec in allergy_rows
                         if rec["ALLERGEN"].strip().upper() not in ("NKA", "NKDA")}
    review_by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mt in review:
        ra, rb = root_of[mt.a], root_of[mt.b]
        later, earlier = max(ra, rb), min(ra, rb)
        review_by_root[later].append({"other": f"P-{earlier}", "score": mt.score, "reasons": mt.reasons,
                                      "pair": [identity.summarize(pat_by_id[mt.a]), identity.summarize(pat_by_id[mt.b])]})
    store.xset(run_id, "meta", "cities", sorted({p["ADDR"].split("^")[2].upper() for p in pats
                                                 if p["ADDR"].count("^") >= 4 and p["ADDR"].split("^")[2]}))
    patients = []
    for root, members in sorted(clusters.items()):
        key = f"P-{root}"
        payload = {"members": [pat_by_id[m] for m in sorted(members)], "primary": root, "a08": {}, "aliases": [],
                   "links": {m: reasons.get(m) for m in members if m != root},
                   "has_allergy_rows": any(m in real_allergy_pats for m in members),
                   "review": review_by_root.get(root, [])}
        patients.append((key, payload, {"channel": "delimited", "table": pm["file"], "id": members}))
        for m in members:
            store.xset(run_id, "pat", m, key)
    counts["Patient"] = store.stage(run_id, "Patient", patients)

    def with_pat(m: dict[str, Any], key_prefix: str = "", kind: str | None = None,
                 extra=None) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        for row, rec in (allergy_rows if m is am else rows_of(m)):
            p = pat_by_id.get(rec["PAT_ID"], {})
            payload: dict[str, Any] = {**rec, "_PAT_FAC": p.get("FAC_ID", ""), "_PAT_DOB": p.get("DOB", "")}
            if kind:
                payload["kind"] = kind
            if extra:
                payload.update(extra(rec, p))
            why = _excluded(m, row)
            if why:
                payload["_excluded"] = why
            src_key = row[m["key"]]
            yield f"{key_prefix}{src_key}", payload, lin(m["file"], src_key)

    simple = {
        "Coverage": None,
        "Encounter": lambda rec, p: {"_DEPT_FAC": dept_fac.get(rec.get("DEPT_ID", ""), "")},
        "Condition": None,
        "AllergyIntolerance": lambda rec, p: {"_NKA_FLAG": p.get("NKA_FLAG", "")},
        "MedicationRequest": None,
        "Appointment": lambda rec, p: {"_SIU": None},
    }
    for rtype, extra in simple.items():
        m = canon.get(rtype)
        if m:
            counts[rtype] = store.stage(run_id, rtype, with_pat(m, extra=extra))
    obs = canon.get("Observation") or []

    def observations() -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        for m in obs:
            yield from with_pat(m, key_prefix="LAB-" if m["kind"] == "lab" else "VT-", kind=m["kind"])
    if obs:
        counts["Observation"] = store.stage(run_id, "Observation", observations())
    store.event(run_id, "staged", counts)
    return counts


def make_factory(binding: dict[str, Any]):
    """A reader-registry factory for a delimited source with a canonical binding."""
    def factory(source: str | Path):
        return DelimitedExport(source, binding), stage_canonical
    return factory
