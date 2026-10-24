"""Bridge run database: staged records, batch ledger, metrics, alerts, questions, rules, loss ledger."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, source TEXT, target TEXT, status TEXT, created_at TEXT, updated_at TEXT,
  config TEXT, pass_count INTEGER DEFAULT 0, pause_reason TEXT
);
CREATE TABLE IF NOT EXISTS records (
  run_id TEXT, rtype TEXT, source_key TEXT, seq INTEGER, status TEXT, source TEXT, lineage TEXT,
  mapped TEXT, fidelity REAL, annotations TEXT, issues TEXT, target_id TEXT, batch_id TEXT,
  held_by TEXT, blocked_by TEXT, note TEXT, updated_at TEXT,
  PRIMARY KEY (run_id, rtype, source_key)
);
CREATE INDEX IF NOT EXISTS ix_records_status ON records(run_id, rtype, status);
CREATE INDEX IF NOT EXISTS ix_records_pending_seq ON records(run_id, rtype, seq) WHERE status='pending';
CREATE INDEX IF NOT EXISTS ix_records_blocked_seq ON records(run_id, rtype, seq) WHERE status='blocked';
CREATE INDEX IF NOT EXISTS ix_records_held ON records(run_id, held_by);
CREATE INDEX IF NOT EXISTS ix_records_batch ON records(run_id, batch_id);
-- Accelerate the work_queue blocker lookup without changing its key semantics.
CREATE INDEX IF NOT EXISTS ix_records_blocker_key
  ON records(run_id, (rtype || '/' || source_key), status);
CREATE TABLE IF NOT EXISTS xref (run_id TEXT, kind TEXT, key TEXT, value TEXT, PRIMARY KEY (run_id, kind, key));
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY, run_id TEXT, rtype TEXT, seq INTEGER, nimbus_batch_id TEXT, status TEXT,
  created_at TEXT, counts TEXT, metrics TEXT
);
-- create_batch repeatedly computes MAX(seq) for the current run.
CREATE INDEX IF NOT EXISTS ix_bridge_batches_run_seq ON batches(run_id, seq);
CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY, run_id TEXT, batch_id TEXT, rtype TEXT, rule TEXT, metric TEXT, observed REAL,
  threshold REAL, severity TEXT, status TEXT, message TEXT, samples TEXT, suggested TEXT, created_at TEXT,
  ack_note TEXT, ack_by TEXT
);
CREATE TABLE IF NOT EXISTS overrides (run_id TEXT, rule TEXT, rtype TEXT, threshold REAL, PRIMARY KEY (run_id, rule, rtype));
CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY, run_id TEXT, kind TEXT, match_key TEXT, status TEXT, blocking INTEGER, prompt TEXT,
  context TEXT, options TEXT, default_option TEXT, created_at TEXT, answer TEXT,
  UNIQUE (run_id, kind, match_key)
);
CREATE TABLE IF NOT EXISTS question_records (
  question_id TEXT, rtype TEXT, source_key TEXT, used_default INTEGER, PRIMARY KEY (question_id, rtype, source_key)
);
CREATE TABLE IF NOT EXISTS rules (
  id TEXT PRIMARY KEY, run_id TEXT, kind TEXT, match_key TEXT, decision TEXT, created_by TEXT, created_at TEXT,
  active INTEGER DEFAULT 1, question_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_rules ON rules(run_id, kind, match_key, active);
CREATE TABLE IF NOT EXISTS loss (
  run_id TEXT, rtype TEXT, source_key TEXT, field TEXT, klass TEXT, original TEXT, note TEXT,
  PRIMARY KEY (run_id, rtype, source_key, field)
);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, at TEXT, kind TEXT, detail TEXT);
"""

# record statuses
PENDING, HELD, BLOCKED, LOADED, REJECTED, DROPPED, SUPERSEDED = (
    "pending", "held", "blocked", "loaded", "rejected", "dropped", "superseded")
TERMINAL_OK = {LOADED, DROPPED, SUPERSEDED}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _j(v: Any) -> str | None:
    return None if v is None else json.dumps(v, default=str)


def _l(v: str | None) -> Any:
    return None if v is None else json.loads(v)


class RunStore:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def tx(self):
        return _Tx(self.db)

    # ---------------------------------------------------------------- runs
    def create_run(self, source: str, target: str, config: dict[str, Any]) -> str:
        rid = f"run-{uuid.uuid4().hex[:8]}"
        self.db.execute("INSERT INTO runs (id, source, target, status, created_at, updated_at, config) VALUES (?,?,?,?,?,?,?)",
                        (rid, source, target, "created", now(), now(), _j(config)))
        self.event(rid, "run_created", {"source": source, "target": target})
        return rid

    def run(self, run_id: str | None = None) -> dict[str, Any]:
        row = (self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone() if run_id
               else self.db.execute("SELECT * FROM runs ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone())
        if row is None:
            raise KeyError(f"run {run_id or '(latest)'} not found")
        d = dict(row)
        d["config"] = _l(d["config"])
        return d

    def set_status(self, run_id: str, status: str, reason: str | None = None) -> None:
        self.db.execute("UPDATE runs SET status=?, pause_reason=?, updated_at=? WHERE id=?", (status, reason, now(), run_id))
        self.event(run_id, "status", {"status": status, "reason": reason})

    def bump_pass(self, run_id: str) -> None:
        self.db.execute("UPDATE runs SET pass_count=pass_count+1 WHERE id=?", (run_id,))

    def event(self, run_id: str, kind: str, detail: dict[str, Any]) -> None:
        self.db.execute("INSERT INTO events (run_id, at, kind, detail) VALUES (?,?,?,?)", (run_id, now(), kind, _j(detail)))

    def events(self, run_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return [{**dict(r), "detail": _l(r["detail"])} for r in self.db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit))]

    # ---------------------------------------------------------------- records
    def stage(self, run_id: str, rtype: str, records: Iterable[tuple[str, dict[str, Any], dict[str, Any]]]) -> int:
        n = 0
        stamp = now()  # one stable staging timestamp per table, not one datetime per row
        with self.tx():
            for i, (key, source, lineage) in enumerate(records):
                self.db.execute(
                    "INSERT OR REPLACE INTO records (run_id, rtype, source_key, seq, status, source, lineage, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)", (run_id, rtype, key, i, PENDING, _j(source), _j(lineage), stamp))
                n += 1
        return n

    def record(self, run_id: str, rtype: str, key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM records WHERE run_id=? AND rtype=? AND source_key=?", (run_id, rtype, key)).fetchone()
        return self._rec(row) if row else None

    def find_record(self, run_id: str, key: str) -> list[dict[str, Any]]:
        return [self._rec(r) for r in self.db.execute(
            "SELECT * FROM records WHERE run_id=? AND (source_key=? OR source_key LIKE ?)", (run_id, key, f"%{key}%"))][:20]

    @staticmethod
    def _rec(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in ("source", "lineage", "mapped", "annotations", "issues"):
            d[k] = _l(d[k])
        return d

    def status_of(self, run_id: str, rtype: str, key: str) -> str | None:
        row = self.db.execute("SELECT status FROM records WHERE run_id=? AND rtype=? AND source_key=?", (run_id, rtype, key)).fetchone()
        return row[0] if row else None

    def work_queue(self, run_id: str, rtype: str, limit: int = -1) -> list[dict[str, Any]]:
        """Pending records plus blocked ones whose blocker has since loaded."""
        rows = self.db.execute(
            """SELECT * FROM (
                 SELECT r.* FROM records r INDEXED BY ix_records_pending_seq
                 WHERE r.run_id=? AND r.rtype=? AND r.status='pending' ORDER BY r.seq LIMIT ?
               )
               UNION ALL
               SELECT * FROM (
                 SELECT r.* FROM records r INDEXED BY ix_records_blocked_seq
                 WHERE r.run_id=? AND r.rtype=? AND r.status='blocked'
                   AND EXISTS (SELECT 1 FROM records b WHERE b.run_id=r.run_id
                     AND b.rtype || '/' || b.source_key=r.blocked_by
                     AND b.status IN ('loaded','superseded')) ORDER BY r.seq LIMIT ?
               )
               ORDER BY seq LIMIT ?""", (run_id, rtype, limit, run_id, rtype, limit, limit))
        return [self._rec(r) for r in rows]

    def update_record(self, run_id: str, rtype: str, key: str, **fields: Any) -> None:
        for k in ("source", "mapped", "annotations", "issues"):
            if k in fields:
                fields[k] = _j(fields[k])
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE records SET {cols} WHERE run_id=? AND rtype=? AND source_key=?",
                        (*fields.values(), run_id, rtype, key))

    def status_counts(self, run_id: str) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.db.execute("SELECT rtype, status, COUNT(*) n FROM records WHERE run_id=? GROUP BY rtype, status", (run_id,)):
            out.setdefault(r["rtype"], {})[r["status"]] = r["n"]
        return out

    def records_by_status(self, run_id: str, status: str, rtype: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM records WHERE run_id=? AND status=?" + (" AND rtype=?" if rtype else "") + " ORDER BY rtype, seq LIMIT ?"
        args = (run_id, status, rtype, limit) if rtype else (run_id, status, limit)
        return [self._rec(r) for r in self.db.execute(sql, args)]

    # ---------------------------------------------------------------- xref
    def xset(self, run_id: str, kind: str, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)", (run_id, kind, key, _j(value)))

    def xget(self, run_id: str, kind: str, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM xref WHERE run_id=? AND kind=? AND key=?", (run_id, kind, key)).fetchone()
        return _l(row[0]) if row else default

    def xall(self, run_id: str, kind: str) -> dict[str, Any]:
        return {r["key"]: _l(r["value"]) for r in self.db.execute("SELECT key, value FROM xref WHERE run_id=? AND kind=?", (run_id, kind))}

    # ---------------------------------------------------------------- batches
    def create_batch(self, run_id: str, rtype: str, nimbus_batch_id: str) -> str:
        seq = self.db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM batches WHERE run_id=?", (run_id,)).fetchone()[0]
        bid = f"{run_id}-b{seq:04d}"
        self.db.execute("INSERT INTO batches VALUES (?,?,?,?,?,?,?,?,?)",
                        (bid, run_id, rtype, seq, nimbus_batch_id, "open", now(), None, None))
        return bid

    def finish_batch(self, batch_id: str, status: str, counts: dict[str, Any], metrics: dict[str, Any]) -> None:
        self.db.execute("UPDATE batches SET status=?, counts=?, metrics=? WHERE id=?", (status, _j(counts), _j(metrics), batch_id))

    def set_batch_status(self, batch_id: str, status: str) -> None:
        self.db.execute("UPDATE batches SET status=? WHERE id=?", (status, batch_id))

    def batches(self, run_id: str, rtype: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM batches WHERE run_id=?", [run_id]
        if rtype:
            sql += " AND rtype=?"
            args.append(rtype)
        if status:
            sql += " AND status=?"
            args.append(status)
        return [{**dict(r), "counts": _l(r["counts"]), "metrics": _l(r["metrics"])}
                for r in self.db.execute(sql + " ORDER BY seq", args)]

    def batch(self, batch_id: str) -> dict[str, Any]:
        r = self.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if r is None:
            raise KeyError(f"batch {batch_id} not found")
        return {**dict(r), "counts": _l(r["counts"]), "metrics": _l(r["metrics"])}

    # ---------------------------------------------------------------- alerts
    def add_alert(self, run_id: str, **a: Any) -> str:
        aid = f"al-{uuid.uuid4().hex[:8]}"
        self.db.execute(
            "INSERT INTO alerts (id, run_id, batch_id, rtype, rule, metric, observed, threshold, severity, status, message,"
            " samples, suggested, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, run_id, a.get("batch_id"), a.get("rtype"), a["rule"], a["metric"], a.get("observed"), a.get("threshold"),
             a["severity"], "open", a["message"], _j(a.get("samples", [])), _j(a.get("suggested", [])), now()))
        return aid

    def alerts(self, run_id: str, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM alerts WHERE run_id=?" + (" AND status=?" if status else "") + " ORDER BY created_at, rowid"
        args = (run_id, status) if status else (run_id,)
        return [{**dict(r), "samples": _l(r["samples"]), "suggested": _l(r["suggested"])} for r in self.db.execute(sql, args)]

    def alert(self, alert_id: str) -> dict[str, Any]:
        r = self.db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if r is None:
            raise KeyError(f"alert {alert_id} not found")
        return {**dict(r), "samples": _l(r["samples"]), "suggested": _l(r["suggested"])}

    def ack_alert(self, alert_id: str, note: str, by: str) -> None:
        self.db.execute("UPDATE alerts SET status='acknowledged', ack_note=?, ack_by=? WHERE id=?", (note, by, alert_id))

    def set_override(self, run_id: str, rule: str, rtype: str, threshold: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO overrides VALUES (?,?,?,?)", (run_id, rule, rtype, threshold))

    def overrides(self, run_id: str) -> dict[tuple[str, str], float]:
        return {(r["rule"], r["rtype"]): r["threshold"] for r in self.db.execute("SELECT * FROM overrides WHERE run_id=?", (run_id,))}

    # ---------------------------------------------------------------- questions & rules
    def upsert_question(self, run_id: str, kind: str, match_key: str, prompt: str, options: list[dict[str, Any]],
                        blocking: bool, context: dict[str, Any], default_option: str | None) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM questions WHERE run_id=? AND kind=? AND match_key=?", (run_id, kind, match_key)).fetchone()
        if row is None:
            qid = f"q-{uuid.uuid4().hex[:8]}"
            self.db.execute(
                "INSERT INTO questions (id, run_id, kind, match_key, status, blocking, prompt, context, options, default_option, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (qid, run_id, kind, match_key, "open", int(blocking), prompt, _j(context), _j(options), default_option, now()))
            row = self.db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        return self._q(row)

    def link_question(self, question_id: str, rtype: str, key: str, used_default: bool) -> None:
        self.db.execute("INSERT OR REPLACE INTO question_records VALUES (?,?,?,?)", (question_id, rtype, key, int(used_default)))

    @staticmethod
    def _q(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["blocking"] = bool(d["blocking"])
        for k in ("context", "options", "answer"):
            d[k] = _l(d[k])
        return d

    def question(self, qid: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        if row is None:
            raise KeyError(f"question {qid} not found")
        q = self._q(row)
        q["affected"] = [dict(r) for r in self.db.execute(
            "SELECT rtype, source_key, used_default FROM question_records WHERE question_id=? ORDER BY source_key", (qid,))]
        return q

    def questions(self, run_id: str, status: str | None = "open", kind: str | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT q.*, (SELECT COUNT(*) FROM question_records qr WHERE qr.question_id=q.id) AS affected_count"
               " FROM questions q WHERE q.run_id=?")
        args: list[Any] = [run_id]
        if status:
            sql += " AND q.status=?"
            args.append(status)
        if kind:
            sql += " AND q.kind=?"
            args.append(kind)
        sql += " ORDER BY q.blocking DESC, affected_count DESC, q.created_at"
        return [{**self._q(r), "affected_count": r["affected_count"]} for r in self.db.execute(sql, args)]

    def answer_question(self, qid: str, answer: dict[str, Any]) -> None:
        self.db.execute("UPDATE questions SET status='answered', answer=? WHERE id=?", (_j(answer), qid))

    def add_rule(self, run_id: str, kind: str, match_key: str, decision: dict[str, Any], created_by: str,
                 question_id: str | None = None) -> str:
        self.db.execute("UPDATE rules SET active=0 WHERE run_id=? AND kind=? AND match_key=?", (run_id, kind, match_key))
        rid = f"rule-{uuid.uuid4().hex[:8]}"
        self.db.execute("INSERT INTO rules (id, run_id, kind, match_key, decision, created_by, created_at, question_id)"
                        " VALUES (?,?,?,?,?,?,?,?)", (rid, run_id, kind, match_key, _j(decision), created_by, now(), question_id))
        return rid

    def rule(self, run_id: str, kind: str, match_key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT decision FROM rules WHERE run_id=? AND kind=? AND match_key=? AND active=1",
                              (run_id, kind, match_key)).fetchone()
        return _l(row[0]) if row else None

    def rules(self, run_id: str, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM rules WHERE run_id=?" + (" AND active=1" if active_only else "") + " ORDER BY created_at"
        return [{**dict(r), "decision": _l(r["decision"])} for r in self.db.execute(sql, (run_id,))]

    def retire_rule(self, rule_id: str) -> None:
        self.db.execute("UPDATE rules SET active=0 WHERE id=?", (rule_id,))

    # ---------------------------------------------------------------- loss & metrics
    def record_loss(self, run_id: str, rtype: str, key: str, losses: list[dict[str, Any]]) -> None:
        self.db.execute("DELETE FROM loss WHERE run_id=? AND rtype=? AND source_key=?", (run_id, rtype, key))
        for l in losses:
            self.db.execute("INSERT OR REPLACE INTO loss VALUES (?,?,?,?,?,?,?)",
                            (run_id, rtype, key, l["field"], l["klass"], _j(l.get("original")), l.get("note")))

    def loss_summary(self, run_id: str, rtype: str | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT l.rtype, l.field, l.klass, COUNT(*) n, MIN(l.note) example FROM loss l JOIN records r"
               " ON r.run_id=l.run_id AND r.rtype=l.rtype AND r.source_key=l.source_key"
               " WHERE l.run_id=? AND r.status IN ('loaded','dropped','superseded')")
        args: list[Any] = [run_id]
        if rtype:
            sql += " AND l.rtype=?"
            args.append(rtype)
        sql += " GROUP BY l.rtype, l.field, l.klass ORDER BY n DESC"
        return [dict(r) for r in self.db.execute(sql, args)]


class _Tx:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self):
        self.db.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, *_):
        self.db.execute("ROLLBACK" if exc_type else "COMMIT")
