"""Index must preserve work-queue semantics for loaded, pending and blocked records."""
from bridge.runs.store import RunStore


def test_blocker_index_exists_and_work_queue_semantics(env):
    store, _, _ = env
    rid = store.create_run("synthetic", "embedded::memory:", {"types": ["Patient", "Encounter"]})
    store.stage(rid, "Patient", [("P1", {}, {}), ("P2", {}, {})])
    store.stage(rid, "Encounter", [("E1", {}, {}), ("E2", {}, {}), ("E3", {}, {})])
    store.update_record(rid, "Encounter", "E1", status="blocked", blocked_by="Patient/P1")
    store.update_record(rid, "Encounter", "E2", status="blocked", blocked_by="Patient/P2")
    store.update_record(rid, "Encounter", "E3", status="held")
    assert store.work_queue(rid, "Encounter") == []
    store.update_record(rid, "Patient", "P1", status="loaded")
    assert [r["source_key"] for r in store.work_queue(rid, "Encounter")] == ["E1"]
    store.update_record(rid, "Patient", "P2", status="superseded")
    assert [r["source_key"] for r in store.work_queue(rid, "Encounter")] == ["E1", "E2"]
    store.update_record(rid, "Encounter", "E1", status="pending")
    assert [r["source_key"] for r in store.work_queue(rid, "Encounter", limit=1)] == ["E1"]
    indexes = {row["name"] for row in store.db.execute("PRAGMA index_list(records)")}
    assert "ix_records_blocker_key" in indexes


def test_blocker_index_used_in_query_plan(env):
    store, _, _ = env
    plan = [row[3] for row in store.db.execute(
        """EXPLAIN QUERY PLAN SELECT r.* FROM records r
           WHERE r.run_id=? AND r.rtype=? AND
             (r.status='pending' OR (r.status='blocked' AND
             EXISTS (SELECT 1 FROM records b WHERE b.run_id=r.run_id
               AND b.rtype || '/' || b.source_key = r.blocked_by
               AND b.status IN ('loaded','superseded'))))
           ORDER BY r.seq LIMIT ?""", ("run-1", "Encounter", -1))]
    assert any("ix_records_blocker_key" in row for row in plan), plan
