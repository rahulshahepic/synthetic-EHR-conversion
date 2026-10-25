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

    store.xset(run_id, "meta", "facilities", sorted(fac))
    store.xset(run_id, "meta", "facility_names", {k: v["FAC_NAME"] for k, v in fac.items()})
    store.xset(run_id, "meta", "manifest_notes", export.manifest.get("notes", {}))

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
        g = lambda path: msg.get(path) or ""  # noqa: E731
        ev = (msg.type or "").split("^")[-1]
        pid = mrn_to_pat.get((g("PID-3.4"), g("PID-3.1")))
        if ev == "A40":
            retired = mrn_to_pat.get((g("MRG-1.4"), g("MRG-1.1")))
            if pid and retired:
                merges.append((pid, retired))
        elif ev == "A08" and pid:
            when = g("MSH-7")
            if when[:8] > pat_by_id[pid]["LAST_UPD"] and when > a08.get(pid, {}).get("at", ""):
                a08[pid] = {"at": when, "control_id": msg.control_id,
                            "addr": "^".join(g(f"PID-11.{i}") for i in range(1, 6)), "phone": g("PID-13")}

    # --- identity
    # A generated profile may state the merge policy
    # (MERGE_POLICY="route_to_reconciliation"): then staging must not
    # auto-group charts at all — deterministic and A40 links alike become
    # review candidates for a human. The hand-written control profile
    # carries no MERGE_POLICY and keeps the automatic behavior.
    auto_merge = getattr(profile, "MERGE_POLICY", None) != "route_to_reconciliation"
    clusters, review, reasons = identity.resolve(pats, merges, auto_merge=auto_merge)
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
    store.xset(run_id, "meta", "cities", sorted({p["ADDR"].split("^")[2].upper() for p in pats
                                                 if p["ADDR"].count("^") >= 4 and p["ADDR"].split("^")[2]}))
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
    counts["MedicationRequest"] = store.stage(run_id, "MedicationRequest", with_pat(export.table("MED_ORD", "ORD_ID"), "MED_ORD", "ORD_ID"))
    counts["Observation"] = store.stage(run_id, "Observation", _observations(export, pat_by_id, mrn_to_pat))
    counts["Immunization"] = store.stage(run_id, "Immunization", _immunizations(export, pat_by_id, mrn_to_pat))
    counts["DocumentReference"] = store.stage(run_id, "DocumentReference", with_pat(export.table("NOTE", "NOTE_ID"), "NOTE", "NOTE_ID"))
    siu: dict[str, dict[str, str]] = {}
    for msg in export.messages("siu"):
        aid, when = msg.get("SCH-1") or "", msg.get("MSH-7") or ""
        if aid and when >= siu.get(aid, {}).get("at", ""):
            siu[aid] = {"at": when, "status": msg.get("SCH-25") or "", "event": msg.type, "control_id": msg.control_id}
    counts["Appointment"] = store.stage(run_id, "Appointment", with_pat(
        export.table("SCHED", "APPT_ID"), "SCHED", "APPT_ID", lambda r: {"_SIU": siu.get(r["APPT_ID"])}))
    master = {r["CHG_CODE"]: r for r in export.extract_csv("charge_master.csv")}
    counts["ChargeItem"] = store.stage(run_id, "ChargeItem", with_pat(
        export.table("CHARGE", "CHG_ID"), "CHARGE", "CHG_ID", lambda r: {"_CDM": master.get(r["CHG_CODE"])}))
    counts["UserAccount"] = store.stage(run_id, "UserAccount",
                                        ((u["USER_ID"], u, _l(u, "USERS", "USER_ID")) for u in export.table("USERS", "USER_ID")))
    store.event(run_id, "staged", counts)
    return counts


VITAL_FIELDS = ("BP", "PULSE", "RESP", "TEMP", "WT", "HT", "SPO2")


def _observations(export: HalcyonExport, pat_by_id: dict[str, dict[str, str]],
                  mrn_to_pat: dict[tuple[str, str], str]) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Labs from LAB_RESULT and ORU (feed newer; corrected results override), vitals expanded per measurement."""
    labs: dict[str, dict[str, Any]] = {}
    for r in export.table("LAB_RESULT", "RES_ID"):
        key = f"LAB-{r['ACCESSION']}:{r['TEST_CODE']}"
        labs[key] = {"kind": "lab", **r, "_PAT_FAC": pat_by_id.get(r["PAT_ID"], {}).get("FAC_ID", ""),
                     "_STATUS": "F", "_lineage": {"channel": "db", "table": "LAB_RESULT", "id": r["RES_ID"]}}
    for msg in export.messages("oru"):
        def g(path: str, i: int = 0) -> str:
            return msg.get(path, seg_index=i) or ""
        pat_id = mrn_to_pat.get((g("PID-3.4"), g("PID-3.1")))
        acc = g("OBR-3")
        for i in range(sum(1 for seg in msg.segments if seg.name == "OBX")):
            code = g("OBX-3.1", i)
            key = f"LAB-{acc}:{code}"
            feed = {"TEST_CODE": code, "TEST_NAME": g("OBX-3.2", i), "RESULT_VAL": g("OBX-5", i),
                    "UNITS": g("OBX-6", i), "REF_RANGE": g("OBX-7", i), "ABN_FLAG": g("OBX-8", i),
                    "COLLECT_DT": g("OBX-14", i), "_STATUS": g("OBX-11", i) or "F"}
            lin = {"channel": "hl7", "message": msg.control_id, "segment": f"OBX[{i + 1}]"}
            if key in labs:
                if feed["_STATUS"] == "C":
                    labs[key].update(feed, _corrected_from=labs[key]["RESULT_VAL"], _lineage={**labs[key]["_lineage"], "override": lin})
            elif pat_id:
                labs[key] = {"kind": "lab", "PAT_ID": pat_id, "VISIT_ID": "", "ACCESSION": acc, **feed,
                             "_PAT_FAC": pat_by_id[pat_id]["FAC_ID"], "_lineage": lin}
    for key, payload in labs.items():
        yield key, payload, payload.pop("_lineage")
    for v in export.table("VITALS", "VITAL_ID"):
        fac = pat_by_id.get(v["PAT_ID"], {}).get("FAC_ID", "")
        for f in VITAL_FIELDS:
            if v[f].strip():
                yield (f"VT-{v['VITAL_ID']}:{f}",
                       {"kind": "vital", "FIELD": f, "VALUE": v[f], "PAT_ID": v["PAT_ID"], "VISIT_ID": v["VISIT_ID"],
                        "TAKEN_DT": v["TAKEN_DT"], "_PAT_FAC": fac},
                       {"channel": "db", "table": "VITALS", "id": v["VITAL_ID"], "column": f})


def _immunizations(export: HalcyonExport, pat_by_id: dict[str, dict[str, str]],
                   mrn_to_pat: dict[tuple[str, str], str]) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """DB is authoritative; registry rows matching a DB row (same patient + CVX within 31 days) annotate it,
    unmatched registry rows become their own records."""
    from datetime import datetime
    from ..terminology import TERMS
    rows = export.table("IMMUN", "IMM_ID")
    by_pat_cvx: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    out = []
    for r in rows:
        payload = {"source": "db", **r, "_PAT_FAC": pat_by_id.get(r["PAT_ID"], {}).get("FAC_ID", ""), "_REGISTRY": None}
        cvx = TERMS.vaccines.get(r["VACCINE_CODE"], (None,))[0]
        if cvx:
            by_pat_cvx[(r["PAT_ID"], cvx)].append(payload)
        out.append((r["IMM_ID"], payload, _l(r, "IMMUN", "IMM_ID")))
    for i, reg in enumerate(export.extract_csv("immunizations.csv", delimiter="|", encoding="latin-1")):
        pat_id = mrn_to_pat.get((reg["FAC"], reg["MRN"]))
        try:
            d = datetime.strptime(reg["ADMIN_DATE"], "%m/%d/%Y").date()
        except ValueError:
            continue
        match = None
        for cand in by_pat_cvx.get((pat_id, reg["CVX"]), []):
            cd = datetime.strptime(cand["ADMIN_DT"], "%Y%m%d").date()
            if abs((cd - d).days) <= 31 and cand["_REGISTRY"] is None:
                match = cand
                break
        if match:
            match["_REGISTRY"] = {**reg, "row": i + 2}
        elif pat_id:
            key = f"REG-{reg['FAC']}-{reg['MRN']}-{reg['CVX']}-{d.isoformat()}"
            out.append((key, {"source": "registry", "PAT_ID": pat_id, "VACCINE_CODE": reg["CVX"], "VACCINE_NAME": reg["VACCINE"],
                              "ADMIN_DT": d.strftime("%Y%m%d"), "LOT": reg["LOT"], "_PAT_FAC": pat_by_id[pat_id]["FAC_ID"],
                              "_REGISTRY": None}, {"channel": "csv", "file": "immunizations.csv", "row": i + 2}))
    yield from out
