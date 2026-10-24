"""Cutover delta support: compare with the prior rehearsal/run and summarize what changed."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from . import store as S


def stage_source_deletions(store: S.RunStore, run_id: str, prior_run_db: str) -> int:
    """Records loaded by the prior run whose source no longer exists are staged as `_retire` records,
    so they surface as questions instead of silently lingering (or silently disappearing)."""
    prior = S.RunStore(prior_run_db)
    prior_run = prior.run()
    n = 0
    with store.tx():
        base_seq = store.db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM records WHERE run_id=?", (run_id,)).fetchone()[0]
        for row in prior.db.execute("SELECT rtype, source_key, mapped, target_id FROM records WHERE run_id=? AND status='loaded'",
                                    (prior_run["id"],)):
            if store.status_of(run_id, row["rtype"], row["source_key"]) is not None:
                continue
            store.db.execute(
                "INSERT INTO records (run_id, rtype, source_key, seq, status, source, lineage, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, row["rtype"], row["source_key"], base_seq + n, S.PENDING,
                 json.dumps({"_retire": True, "prior_mapped": json.loads(row["mapped"]), "prior_target_id": row["target_id"],
                             "prior_run": prior_run["id"]}),
                 json.dumps({"channel": "prior_run", "run": prior_run["id"], "note": "absent from current source"}), S.now()))
            n += 1
        # inherit "which duplicate is the canonical record" so the delta does not flip owners (order-dependent otherwise)
        for row in prior.db.execute("SELECT kind, key, value FROM xref WHERE run_id=? AND kind IN ('dedupe', 'cob')",
                                    (prior_run["id"],)):
            store.db.execute("INSERT OR REPLACE INTO xref VALUES (?,?,?,?)", (run_id, row["kind"], row["key"], row["value"]))
    store.event(run_id, "source_deletions_staged", {"prior_run": prior_run["id"], "records": n})
    return n


def delta_summary(store: S.RunStore, run_id: str | None = None) -> dict[str, Any]:
    rid = store.run(run_id)["id"]
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for b in store.batches(rid):
        if b["status"] != "loaded" or not b["counts"]:
            continue
        for k in ("created", "updated", "unchanged"):
            out[b["rtype"]][k] += b["counts"].get(k, 0)
    for r in store.db.execute("SELECT rtype, COUNT(*) n FROM records WHERE run_id=? AND json_extract(source, '$._retire') = 1 "
                              "GROUP BY rtype", (rid,)):
        out[r["rtype"]]["source_deleted"] = r["n"]
    return {"run_id": rid, "by_type": {t: dict(v) for t, v in sorted(out.items())}}
