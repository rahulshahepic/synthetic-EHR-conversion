"""Read a Halcyon export directory and stage source records per target resource type.

Bridge reads only halcyon.db, manifest.json, feeds/ and extracts/ (never the ground-truth folder).
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from ..mapping import identity
from ..runs.store import RunStore
from . import hl7

ALLOWED = ("halcyon.db", "feeds", "extracts", "manifest.json")


class HalcyonExport:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not (self.path / "halcyon.db").exists():
            raise FileNotFoundError(f"{self.path} is not a Halcyon export (no halcyon.db)")
        self._db = sqlite3.connect(f"file:{self.path / 'halcyon.db'}?mode=ro", uri=True)
        self._db.row_factory = sqlite3.Row

    @property
    def manifest(self) -> dict[str, Any]:
        p = self.path / "manifest.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def table(self, name: str, order: str | None = None) -> list[dict[str, str]]:
        sql = f"SELECT * FROM {name}" + (f" ORDER BY {order}" if order else " ORDER BY rowid")
        return [{k: (v if v is not None else "") for k, v in dict(r).items()} for r in self._db.execute(sql)]

    def messages(self, kind: str) -> Iterator[hl7.Message]:
        for f in sorted((self.path / "feeds").glob(f"{kind}_*.hl7")):
            yield from hl7.iter_messages(f)

    def extract_csv(self, name: str, delimiter: str = ",", encoding: str = "utf-8") -> list[dict[str, str]]:
        with open(self.path / "extracts" / name, encoding=encoding, newline="") as f:
            return list(csv.DictReader(f, delimiter=delimiter))


def _l(row: dict[str, str], table: str, pk: str, channel: str = "db") -> dict[str, Any]:
    return {"channel": channel, "table": table, "id": row[pk]}


def stage_all(store: RunStore, run_id: str, export: HalcyonExport, profile: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    fac = {r["FAC_ID"]: r for r in export.table("FACILITY")}
    depts = export.table("DEPT")
    pats = export.table("PAT", "PAT_ID")
    pat_by_id = {p["PAT_ID"]: p for p in pats}
    mrn_to_pat = {(p["FAC_ID"], p["MRN"]): p["PAT_ID"] for p in pats}

    # --- organizations & locations (Halcyon: facility > dept; Nimbus: system > site > department)
    orgs = [(profile.SYSTEM_ORG["key"], {"kind": "system", "name": profile.SYSTEM_ORG["name"]},
             {"channel": "profile", "note": "Halcyon has no system level; synthesized"})]
    for f in fac.values():
        orgs.append((f"SITE-{f['FAC_ID']}", {"kind": "site", **f}, _l(f, "FACILITY", "FAC_ID")))
    locs = []
    for d in depts:
        sites = [d["FAC_ID"]] if d["FAC_ID"] else sorted(fac)
        for s in sites:
            key = f"{d['DEPT_ID']}@{s}"
            payload = {"kind": "department", **d, "SITE": s, "SHARED": not d["FAC_ID"]}
            orgs.append((f"DEPT-{key}", payload, _l(d, "DEPT", "DEPT_ID")))
            locs.append((f"LOC-{key}", payload, _l(d, "DEPT", "DEPT_ID")))
    counts["Organization"] = store.stage(run_id, "Organization", orgs)
    counts["Location"] = store.stage(run_id, "Location", locs)

    counts["Practitioner"] = store.stage(run_id, "Practitioner",
                                         ((p["PROV_ID"], p, _l(p, "PROVIDER", "PROV_ID")) for p in export.table("PROVIDER", "PROV_ID")))
    counts["Payer"] = store.stage(run_id, "Payer", ((p["PAYER_ID"], p, _l(p, "PAYER", "PAYER_ID")) for p in export.table("PAYER")))
    counts["Plan"] = store.stage(run_id, "Plan", ((p["PLAN_ID"], p, _l(p, "PLAN", "PLAN_ID")) for p in export.table("PLAN")))

    # --- ADT feed: A40 merges, A08 demographic updates
    merges, a08 = [], {}
    for msg in export.messages("adt"):
        ev = msg.type.split("^")[-1]
        pid = mrn_to_pat.get((msg.get("PID-3.4"), msg.get("PID-3.1")))
        if ev == "A40":
            retired = mrn_to_pat.get((msg.get("MRG-1.4"), msg.get("MRG-1.1")))
            if pid and retired:
                merges.append((pid, retired))
        elif ev == "A08" and pid:
            when = msg.get("MSH-7")
            if when[:8] > pat_by_id[pid]["LAST_UPD"] and when > a08.get(pid, {}).get("at", ""):
                a08[pid] = {"at": when, "control_id": msg.control_id,
                            "addr": "^".join(msg.get(f"PID-11.{i}") for i in range(1, 6)), "phone": msg.get("PID-13")}

    # --- identity
    clusters, review, reasons = identity.resolve(pats, merges)
    root_of = {m: root for root, members in clusters.items() for m in members}
    allergies = export.table("ALLERGY", "ALG_ID")
    real_allergy_pats = {a["PAT_ID"] for a in allergies if a["ALLERGEN"].strip().upper() not in ("NKA", "NKDA")}
    aliases = defaultdict(list)
    for a in export.table("PAT_ALIAS"):
        aliases[a["PAT_ID"]].append(a)
    review_by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in review:
        ra, rb = root_of[m.a], root_of[m.b]
        later, earlier = max(ra, rb), min(ra, rb)
        review_by_root[later].append({"other": f"H-{earlier}", "score": m.score, "reasons": m.reasons,
                                      "pair": [identity.summarize(pat_by_id[m.a]), identity.summarize(pat_by_id[m.b])]})
    patients = []
    for root, members in sorted(clusters.items()):
        key = f"H-{root}"
        rows = [pat_by_id[m] for m in sorted(members)]
        payload = {"members": rows, "primary": root, "a08": {m: a08[m] for m in members if m in a08},
                   "aliases": [a for m in members for a in aliases[m]], "links": {m: reasons.get(m) for m in members if m != root},
                   "has_allergy_rows": any(m in real_allergy_pats for m in members), "review": review_by_root.get(root, [])}
        patients.append((key, payload, {"channel": "db+adt", "table": "PAT", "id": members}))
        for m in members:
            store.xset(run_id, "pat", m, key)
    counts["Patient"] = store.stage(run_id, "Patient", patients)

    def with_pat(rows: list[dict[str, str]], table: str, pk: str, extra=None) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
        for r in rows:
            p = pat_by_id.get(r["PAT_ID"], {})
            payload = {**r, "_PAT_FAC": p.get("FAC_ID", ""), "_PAT_DOB": p.get("DOB", "")}
            if extra:
                payload.update(extra(r))
            yield r[pk], payload, _l(r, table, pk)

    dept_fac = {d["DEPT_ID"]: d["FAC_ID"] for d in depts}
    counts["Coverage"] = store.stage(run_id, "Coverage", with_pat(export.table("COVERAGE", "COV_ID"), "COVERAGE", "COV_ID"))
    counts["Encounter"] = store.stage(run_id, "Encounter", with_pat(
        export.table("VISIT", "VISIT_ID"), "VISIT", "VISIT_ID", lambda r: {"_DEPT_FAC": dept_fac.get(r["DEPT_ID"], "")}))
    counts["Condition"] = store.stage(run_id, "Condition", with_pat(export.table("DX", "DX_ID"), "DX", "DX_ID"))
    counts["AllergyIntolerance"] = store.stage(run_id, "AllergyIntolerance", with_pat(
        allergies, "ALLERGY", "ALG_ID", lambda r: {"_NKA_FLAG": pat_by_id.get(r["PAT_ID"], {}).get("NKA_FLAG", "")}))
    store.event(run_id, "staged", counts)
    return counts
