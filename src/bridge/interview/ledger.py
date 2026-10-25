"""Append-only interview ledgers.

A ledger is the record of one import's discovery: profiler observations
imported as events, questions asked, answers received, claims asserted,
disputes opened and resolved. Ledgers are committed in the repo at
``src/bridge/interview/ledgers/<source>.jsonl`` and double as CI fixtures:
spec generation from a ledger is a pure function, so replaying a ledger
must reproduce the same spec byte-for-byte.

Format: one JSON object per line, ``{"id": "E000001", "type": ...,
"payload": {...}}``. Ids are stable and sequential in file order. The file
is append-only: ``append_event`` never rewrites earlier lines.
"""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LedgerEvent:
    id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"id": self.id, "type": self.type, "payload": self.payload},
                          sort_keys=True, ensure_ascii=False)


def event_id(index: int) -> str:
    """Stable id for the (1-based) position of an event in the ledger."""
    return f"E{index:06d}"


def read_events(path: str | Path) -> list[LedgerEvent]:
    p = Path(path)
    if not p.exists():
        return []
    events = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        events.append(LedgerEvent(id=row["id"], type=row["type"], payload=row.get("payload", {})))
    return events


def append_event(path: str | Path, type: str, payload: dict[str, Any]) -> LedgerEvent:
    """Append one event and return it. Earlier lines are never touched.

    The next id is found by counting raw lines under an exclusive file
    lock — no full JSON re-parse of the ledger per append, and two writers
    appending concurrently cannot interleave lines or reuse an id.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)
    with os.fdopen(fd, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            n = sum(1 for line in f if line.strip())
            ev = LedgerEvent(id=event_id(n + 1), type=type, payload=payload)
            f.write(ev.to_json() + "\n")
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return ev


def events_of_type(events: list[LedgerEvent], type: str) -> list[LedgerEvent]:
    return [e for e in events if e.type == type]


def questions(events: list[LedgerEvent]) -> list[LedgerEvent]:
    return events_of_type(events, "question")


def answers(events: list[LedgerEvent]) -> dict[str, LedgerEvent]:
    """Map question event id -> its answer event (latest wins)."""
    out: dict[str, LedgerEvent] = {}
    for e in events_of_type(events, "answer"):
        qid = e.payload.get("question_id")
        if qid:
            out[qid] = e
    return out
