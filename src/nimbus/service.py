"""Nimbus core: storage, import batches, upsert-by-sourceKey, rollback, merge, read APIs.

Storage is a single SQLite file. Every write is recorded in `history` with the batch that made
it and the prior state, which is what makes batch rollback exact.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from . import models as m
from .validation import Issue, iter_refs, parse

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
  rtype TEXT NOT NULL, id TEXT NOT NULL, source_key TEXT, version INTEGER NOT NULL,
  data TEXT NOT NULL, batch_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (rtype, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_resources_sk ON resources(rtype, source_key);
CREATE TABLE IF NOT EXISTS refs (
  owner_rtype TEXT NOT NULL, owner_id TEXT NOT NULL, field TEXT NOT NULL,
  target_rtype TEXT NOT NULL, target_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_refs_target ON refs(target_rtype, target_id);
CREATE INDEX IF NOT EXISTS ix_refs_owner ON refs(owner_rtype, owner_id);
-- Used by repeated per-patient noKnownAllergies and coverage conflict lookups.
CREATE INDEX IF NOT EXISTS ix_refs_owner_target ON refs(owner_rtype, target_id, field);
CREATE TABLE IF NOT EXISTS identifiers (
  system TEXT NOT NULL, value TEXT NOT NULL, patient_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ident ON identifiers(system, value);
-- _unindex() deletes by patient_id on every Patient insert; prevent quadratic scans.
CREATE INDEX IF NOT EXISTS ix_ident_patient ON identifiers(patient_id);
CREATE TABLE IF NOT EXISTS history (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, rtype TEXT NOT NULL, id TEXT NOT NULL,
  batch_id TEXT, op TEXT NOT NULL, prior_data TEXT, prior_version INTEGER,
  prior_batch_id TEXT, prior_source_key TEXT, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_hist_batch ON history(batch_id);
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY, resource_type TEXT NOT NULL, external_batch_id TEXT,
  mode TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, seq INTEGER NOT NULL,
  accepted INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
  unchanged INTEGER NOT NULL DEFAULT 0, system TEXT
);
CREATE INDEX IF NOT EXISTS ix_nimbus_batches_seq ON batches(seq);
CREATE INDEX IF NOT EXISTS ix_resources_rtype_created_id ON resources(rtype, created_at, id);
"""

MAX_RECORDS_PER_CALL = 500


class NimbusError(Exception):
    status = 400

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFound(NimbusError):
    status = 404


class Conflict(NimbusError):
    status = 409


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NimbusService:
    def __init__(self, db_path: str = ":memory:"):
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        if db_path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ batches
    def create_batch(self, resource_type: str, external_batch_id: str | None = None,
                     mode: str = "commit", system: str | None = None) -> dict[str, Any]:
        if resource_type not in m.RESOURCE_MODELS:
            raise NimbusError("E_RESOURCE_TYPE", f"unknown resource type {resource_type!r}")
        if mode not in ("commit", "validate-only"):
            raise NimbusError("E_MODE", "mode must be commit or validate-only")
        with self._lock:
            seq = self._db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM batches").fetchone()[0]
            bid = f"nb-{uuid.uuid4().hex[:12]}"
            self._db.execute(
                "INSERT INTO batches (id, resource_type, external_batch_id, mode, status, created_at, seq, system)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (bid, resource_type, external_batch_id, mode, "open", _now(), seq, system),
            )
        return self.get_batch(bid)

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if row is None:
            raise NotFound("E_NOT_FOUND", f"batch {batch_id} not found")
        d = dict(row)
        return {
            "batchId": d["id"], "resourceType": d["resource_type"], "externalBatchId": d["external_batch_id"],
            "mode": d["mode"], "status": d["status"], "createdAt": d["created_at"],
            "counts": {"accepted": d["accepted"], "rejected": d["rejected"], "unchanged": d["unchanged"]},
        }

    def close_batch(self, batch_id: str) -> dict[str, Any]:
        with self._lock:
            b = self.get_batch(batch_id)
            if b["status"] == "open":
                self._db.execute("UPDATE batches SET status='closed' WHERE id=?", (batch_id,))
        return self.get_batch(batch_id)

    def submit_records(self, batch_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        if len(records) > MAX_RECORDS_PER_CALL:
            raise NimbusError("E_TOO_MANY", f"max {MAX_RECORDS_PER_CALL} records per call")
        with self._lock:
            b = self.get_batch(batch_id)
            if b["status"] != "open":
                raise Conflict("E_BATCH_STATE", f"batch is {b['status']}")
            results = []
            counts = {"accepted": 0, "rejected": 0, "unchanged": 0}
            self._db.execute("BEGIN")
            try:
                for rec in records:
                    res = self._submit_one(b, rec)
                    results.append(res)
                    counts[res["status"] if res["status"] in counts else "accepted"] += 1
                self._db.execute(
                    "UPDATE batches SET accepted=accepted+?, rejected=rejected+?, unchanged=unchanged+? WHERE id=?",
                    (counts["accepted"], counts["rejected"], counts["unchanged"], batch_id),
                )
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return {"batchId": batch_id, "results": results}

    def _submit_one(self, batch: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
        rt = batch["resourceType"]
        sk = rec.get("sourceKey")
        payload = rec.get("resource")
        out: dict[str, Any] = {"sourceKey": sk}
        if not sk or not isinstance(payload, dict):
            return {**out, "status": "rejected", "issues": [Issue("E_REQUIRED", "sourceKey and resource required").to_dict()]}
        model, issues = parse(rt, payload)
        if model is not None:
            issues += self._resolve_refs(rt, model)
        existing = self._row_by_sk(rt, sk)
        if model is not None and not any(i.severity == "error" for i in issues):
            issues += self._contextual_checks(rt, model, existing["id"] if existing else None)
        errors = [i for i in issues if i.severity == "error"]
        out["issues"] = [i.to_dict() for i in issues]
        if errors:
            return {**out, "status": "rejected"}
        if batch["mode"] == "validate-only":
            return {**out, "status": "valid"}

        data = m.dump(model)
        now = _now()
        if existing is not None:
            if json.loads(existing["data"]) == data:
                return {**out, "status": "unchanged", "operation": "unchanged", "targetId": existing["id"]}
            rid = existing["id"]
            self._record_history(rt, rid, batch["batchId"], "update", existing)
            self._db.execute(
                "UPDATE resources SET data=?, version=version+1, batch_id=?, updated_at=? WHERE rtype=? AND id=?",
                (json.dumps(data), batch["batchId"], now, rt, rid),
            )
        else:
            rid = str(uuid.uuid4())
            self._record_history(rt, rid, batch["batchId"], "create", None)
            self._db.execute(
                "INSERT INTO resources (rtype, id, source_key, version, data, batch_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (rt, rid, sk, 1, json.dumps(data), batch["batchId"], now, now),
            )
        self._index(rt, rid, data)
        return {**out, "status": "accepted", "operation": "updated" if existing is not None else "created", "targetId": rid}

    # ------------------------------------------------------------------ helpers
    def _row_by_sk(self, rt: str, sk: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM resources WHERE rtype=? AND source_key=?", (rt, sk)).fetchone()

    def _row(self, rt: str, rid: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM resources WHERE rtype=? AND id=?", (rt, rid)).fetchone()

    def _resolve_refs(self, rt: str, model: Any) -> list[Issue]:
        issues = []
        for field, ref, target in iter_refs(rt, model):
            row = None
            if ref.id:
                row = self._row(target, ref.id)
            elif ref.sourceKey:
                rtype, _, key = ref.sourceKey.partition("/")
                if rtype != target or not key:
                    issues.append(Issue("E_REF_TYPE", f"{field} must reference {target} ('{target}/<key>')", field))
                    continue
                row = self._row_by_sk(target, key)
            else:
                issues.append(Issue("E_REQUIRED", "reference needs id or sourceKey", field))
                continue
            if row is None:
                issues.append(Issue("E_REF_UNRESOLVED", f"{field} -> {ref.id or ref.sourceKey} not found", field))
                continue
            ref.id = row["id"]
            ref.sourceKey = f"{target}/{row['source_key']}" if row["source_key"] else None
            if target == "Patient" and not json.loads(row["data"]).get("active", True):
                issues.append(Issue("W_INACTIVE_PATIENT", "references an inactive (merged) patient", field, "warning"))
        return issues

    def _contextual_checks(self, rt: str, model: Any, self_id: str | None) -> list[Issue]:
        issues: list[Issue] = []
        if rt == "Organization" and model.partOf is not None:
            parent = json.loads(self._row("Organization", model.partOf.id)["data"])
            expected = {"site": "system", "department": "site"}.get(model.type)
            if expected is None or parent["type"] != expected:
                issues.append(Issue("E_HIERARCHY", f"{model.type} cannot be partOf a {parent['type']}", "partOf"))
        elif rt == "Location":
            dept = json.loads(self._row("Organization", model.department.id)["data"])
            if dept["type"] != "department":
                issues.append(Issue("E_HIERARCHY", "Location.department must be a department", "department"))
        elif rt == "Patient":
            for i, ident in enumerate(model.identifiers):
                for row in self._db.execute(
                    "SELECT patient_id FROM identifiers WHERE system=? AND value=?", (ident.system, ident.value)
                ):
                    if row["patient_id"] == self_id:
                        continue
                    other = self._row("Patient", row["patient_id"])
                    if other is not None and json.loads(other["data"]).get("active", True):
                        issues.append(Issue("E_DUPLICATE_IDENTITY",
                                            f"identifier {ident.system}|{ident.value} belongs to patient {row['patient_id']}",
                                            f"identifiers[{i}]"))
            if model.noKnownAllergies and self_id and self._count_refs("AllergyIntolerance", self_id):
                issues.append(Issue("E_CONFLICT", "noKnownAllergies=true but patient has allergy records", "noKnownAllergies"))
        elif rt == "AllergyIntolerance":
            pat = json.loads(self._row("Patient", model.patient.id)["data"])
            if pat.get("noKnownAllergies"):
                issues.append(Issue("E_CONFLICT", "patient is flagged noKnownAllergies", "patient"))
        elif rt == "Coverage":
            for row in self._db.execute(
                "SELECT r.id, r.data FROM refs f JOIN resources r ON r.rtype=f.owner_rtype AND r.id=f.owner_id"
                " WHERE f.owner_rtype='Coverage' AND f.field='patient' AND f.target_id=?", (model.patient.id,)
            ):
                if row["id"] != self_id and json.loads(row["data"]).get("order") == model.order:
                    issues.append(Issue("E_CONFLICT", f"patient already has a coverage with order {model.order}", "order"))
        return issues

    def _count_refs(self, owner_rt: str, target_id: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM refs WHERE owner_rtype=? AND target_id=?", (owner_rt, target_id)
        ).fetchone()[0]

    def _record_history(self, rt: str, rid: str, batch_id: str | None, op: str, prior: sqlite3.Row | None) -> None:
        self._db.execute(
            "INSERT INTO history (rtype, id, batch_id, op, prior_data, prior_version, prior_batch_id, prior_source_key, at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (rt, rid, batch_id, op,
             prior["data"] if prior else None, prior["version"] if prior else None,
             prior["batch_id"] if prior else None, prior["source_key"] if prior else None, _now()),
        )

    def _index(self, rt: str, rid: str, data: dict[str, Any]) -> None:
        self._unindex(rt, rid)
        model = m.RESOURCE_MODELS[rt].model_validate(data)
        for field, ref, target in iter_refs(rt, model):
            if ref.id:
                self._db.execute("INSERT INTO refs VALUES (?,?,?,?,?)", (rt, rid, field, target, ref.id))
        if rt == "Patient":
            for ident in data.get("identifiers", []):
                self._db.execute("INSERT INTO identifiers VALUES (?,?,?)", (ident["system"], ident["value"], rid))

    def _unindex(self, rt: str, rid: str) -> None:
        self._db.execute("DELETE FROM refs WHERE owner_rtype=? AND owner_id=?", (rt, rid))
        if rt == "Patient":
            self._db.execute("DELETE FROM identifiers WHERE patient_id=?", (rid,))

    # ------------------------------------------------------------------ rollback
    def rollback_batch(self, batch_id: str, cascade: bool = False) -> dict[str, Any]:
        with self._lock:
            b = self.get_batch(batch_id)
            if b["status"] == "rolled_back":
                return {**b, "rolledBack": [], "alreadyRolledBack": True}
            blockers = self._rollback_blockers(batch_id)
            rolled: list[str] = []
            if blockers:
                if not cascade:
                    raise Conflict("E_DEPENDENTS", "later batches depend on records written by this batch",
                                   {"blockingBatches": sorted(blockers)})
                for dep in self._order_newest_first(blockers):
                    rolled += self.rollback_batch(dep, cascade=True)["rolledBack"]
            self._db.execute("BEGIN")
            try:
                for h in self._db.execute(
                    "SELECT * FROM history WHERE batch_id=? ORDER BY seq DESC", (batch_id,)
                ).fetchall():
                    self._undo(h)
                self._db.execute("UPDATE batches SET status='rolled_back' WHERE id=?", (batch_id,))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            rolled.append(batch_id)
            return {**self.get_batch(batch_id), "rolledBack": rolled}

    def _order_newest_first(self, batch_ids: set[str]) -> list[str]:
        q = ",".join("?" * len(batch_ids))
        return [r[0] for r in self._db.execute(
            f"SELECT id FROM batches WHERE id IN ({q}) ORDER BY seq DESC", tuple(batch_ids))]

    def _rollback_blockers(self, batch_id: str) -> set[str]:
        """Other live batches that overwrote, or reference, records this batch created/changed."""
        hist = self._db.execute("SELECT rtype, id, op FROM history WHERE batch_id=?", (batch_id,)).fetchall()
        touched = {(h["rtype"], h["id"]) for h in hist}
        created = {(h["rtype"], h["id"]) for h in hist if h["op"] == "create"}
        blockers: set[str] = set()
        for rt, rid in touched:
            row = self._row(rt, rid)
            if row is not None and row["batch_id"] not in (batch_id, None):
                blockers.add(row["batch_id"])
            for later in self._db.execute(
                "SELECT DISTINCT h.batch_id FROM history h JOIN batches b ON b.id=h.batch_id"
                " WHERE h.rtype=? AND h.id=? AND b.status!='rolled_back' AND b.seq >"
                " (SELECT seq FROM batches WHERE id=?)", (rt, rid, batch_id)
            ):
                blockers.add(later[0])
            if (rt, rid) not in created:  # updated records are restored, not deleted: references stay valid
                continue
            for ref in self._db.execute(
                "SELECT r.batch_id FROM refs f JOIN resources r ON r.rtype=f.owner_rtype AND r.id=f.owner_id"
                " WHERE f.target_rtype=? AND f.target_id=?", (rt, rid)
            ):
                if ref["batch_id"] and ref["batch_id"] != batch_id:
                    blockers.add(ref["batch_id"])
        blockers.discard(batch_id)
        return blockers

    def _undo(self, h: sqlite3.Row) -> None:
        rt, rid = h["rtype"], h["id"]
        if h["op"] == "create":
            self._unindex(rt, rid)
            self._db.execute("DELETE FROM resources WHERE rtype=? AND id=?", (rt, rid))
        else:
            self._db.execute(
                "UPDATE resources SET data=?, version=?, batch_id=?, updated_at=? WHERE rtype=? AND id=?",
                (h["prior_data"], h["prior_version"], h["prior_batch_id"], _now(), rt, rid),
            )
            self._index(rt, rid, json.loads(h["prior_data"]))

    # ------------------------------------------------------------------ merge
    def merge_patients(self, target_id: str, source_id: str, import_batch_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if target_id == source_id:
                raise NimbusError("E_VALUE", "cannot merge a patient into itself")
            tgt, src = self._row("Patient", target_id), self._row("Patient", source_id)
            if tgt is None or src is None:
                raise NotFound("E_NOT_FOUND", "patient not found")
            src_data, tgt_data = json.loads(src["data"]), json.loads(tgt["data"])
            if not src_data.get("active", True):
                raise Conflict("E_ALREADY_MERGED", "source patient already inactive")
            if import_batch_id:
                self.get_batch(import_batch_id)
            self._db.execute("BEGIN")
            try:
                moved = 0
                for f in self._db.execute(
                    "SELECT owner_rtype, owner_id, field FROM refs WHERE target_rtype='Patient' AND target_id=?",
                    (source_id,),
                ).fetchall():
                    row = self._row(f["owner_rtype"], f["owner_id"])
                    data = json.loads(row["data"])
                    data[f["field"]] = {"id": target_id, "sourceKey": f"Patient/{tgt['source_key']}"}
                    self._write_existing(f["owner_rtype"], row, data, import_batch_id, "merge")
                    moved += 1
                src_data["active"] = False
                self._write_existing("Patient", src, src_data, import_batch_id, "merge")
                known = {(i["system"], i["value"]) for i in tgt_data["identifiers"]}
                tgt_data["identifiers"] += [i for i in src_data["identifiers"] if (i["system"], i["value"]) not in known]
                if src_data.get("noKnownAllergies") is False:
                    tgt_data["noKnownAllergies"] = tgt_data.get("noKnownAllergies", False) and not self._count_refs(
                        "AllergyIntolerance", target_id)
                self._write_existing("Patient", tgt, tgt_data, import_batch_id, "merge")
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            return {"targetId": target_id, "sourceId": source_id, "movedReferences": moved}

    def _write_existing(self, rt: str, row: sqlite3.Row, data: dict[str, Any], batch_id: str | None, op: str) -> None:
        self._record_history(rt, row["id"], batch_id, op, row)
        self._db.execute(
            "UPDATE resources SET data=?, version=version+1, batch_id=COALESCE(?, batch_id), updated_at=?"
            " WHERE rtype=? AND id=?",
            (json.dumps(data), batch_id, _now(), rt, row["id"]),
        )
        self._index(rt, row["id"], data)

    # ------------------------------------------------------------------ reads
    def _out(self, rt: str, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "resourceType": rt, "id": row["id"], "sourceKey": row["source_key"],
            "meta": {"version": row["version"], "updatedAt": row["updated_at"]},
            "provenance": {"importBatchId": row["batch_id"]},
            **json.loads(row["data"]),
        }

    def get(self, rt: str, rid: str) -> dict[str, Any]:
        row = self._row(rt, rid)
        if row is None:
            raise NotFound("E_NOT_FOUND", f"{rt}/{rid} not found")
        return self._out(rt, row)

    def search(self, rt: str, source_key: str | None = None, identifier: str | None = None,
               patient: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if rt not in m.RESOURCE_MODELS:
            raise NimbusError("E_RESOURCE_TYPE", f"unknown resource type {rt!r}")
        sql, args = "SELECT r.* FROM resources r", []
        where = ["r.rtype=?"]
        args.append(rt)
        if source_key:
            where.append("r.source_key=?")
            args.append(source_key)
        if identifier:
            system, _, value = identifier.partition("|")
            where.append("r.id IN (SELECT patient_id FROM identifiers WHERE system=? AND value=?)")
            args += [system, value]
        if patient:
            where.append("r.id IN (SELECT owner_id FROM refs WHERE owner_rtype=? AND target_rtype='Patient' AND target_id=?)")
            args += [rt, patient]
        sql += " WHERE " + " AND ".join(where) + " ORDER BY r.created_at, r.id LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [self._out(rt, r) for r in self._db.execute(sql, args)]

    def count(self, rt: str) -> dict[str, Any]:
        if rt not in m.RESOURCE_MODELS:
            raise NimbusError("E_RESOURCE_TYPE", f"unknown resource type {rt!r}")
        total = self._db.execute("SELECT COUNT(*) FROM resources WHERE rtype=?", (rt,)).fetchone()[0]
        inactive = self._db.execute(
            "SELECT COUNT(*) FROM resources WHERE rtype=? AND json_extract(data, '$.active') = 0", (rt,)
        ).fetchone()[0]
        return {"resourceType": rt, "total": total, "active": total - inactive}

    def counts(self) -> dict[str, int]:
        return {rt: self.count(rt)["total"] for rt in m.RESOURCE_MODELS}
