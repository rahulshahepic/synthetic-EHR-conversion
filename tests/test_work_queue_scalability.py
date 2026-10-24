"""Regression coverage for bounded work queue and blocked release ordering."""
from bridge.runs.store import RunStore, PENDING, BLOCKED, LOADED


def test_bounded_work_queue(tmp_path):
    store = RunStore(str(tmp_path / "queue.db"))
    run = store.create_run("test", "nimbus", {"types": ["Patient"]})
    store.stage(run, "Patient", ((f"p{i}", {"i": i}, {}) for i in range(200)))
    first = store.work_queue(run, "Patient", 5)
    assert [r["source_key"] for r in first] == [f"p{i}" for i in range(5)]
    for r in first:
        store.update_record(run, "Patient", r["source_key"], status=LOADED)
    assert [r["source_key"] for r in store.work_queue(run, "Patient", 5)] == [f"p{i}" for i in range(5, 10)]


def test_blocked_record_released_by_loaded_dependency(tmp_path):
    store = RunStore(str(tmp_path / "blocked.db"))
    run = store.create_run("test", "nimbus", {"types": ["Patient"]})
    store.stage(run, "Patient", [("p0", {}, {}), ("p1", {}, {})])
    store.update_record(run, "Patient", "p1", status=BLOCKED, blocked_by="Patient/p0")
    assert [r["source_key"] for r in store.work_queue(run, "Patient", 5)] == ["p0"]
    store.update_record(run, "Patient", "p0", status=LOADED)
    assert [r["source_key"] for r in store.work_queue(run, "Patient", 5)] == ["p1"]


def test_dependency_transition_wakes_blocked_rows_without_queue_scan(tmp_path):
    store = RunStore(str(tmp_path / "wakeup.db"))
    run = store.create_run("test", "nimbus", {"types": ["Patient", "Encounter"]})
    store.stage(run, "Patient", [("p0", {}, {})])
    store.stage(run, "Encounter", [("e0", {}, {}), ("e1", {}, {})])
    for key in ("e0", "e1"):
        store.update_record(run, "Encounter", key, status=BLOCKED, blocked_by="Patient/p0")
    assert store.work_queue(run, "Encounter") == []
    store.update_record(run, "Patient", "p0", status=LOADED)
    ready = store.work_queue(run, "Encounter")
    assert [r["source_key"] for r in ready] == ["e0", "e1"]
    assert all(r["status"] == PENDING and r["blocked_by"] is None for r in ready)
    assert all(r["note"] == "released by Patient/p0" for r in ready)
    plan = " ".join(row[3] for row in store.db.execute(
        "EXPLAIN QUERY PLAN UPDATE records SET status='pending' WHERE run_id=? AND blocked_by=? AND status='blocked'",
        (run, "Patient/p0")))
    assert "ix_records_waiting_on" in plan, plan


def test_legacy_blocked_rows_are_released_on_resume(tmp_path):
    store = RunStore(str(tmp_path / "resume.db"))
    run = store.create_run("test", "nimbus", {"types": ["Patient"]})
    store.stage(run, "Patient", [("p0", {}, {}), ("p1", {}, {})])
    store.update_record(run, "Patient", "p1", status=BLOCKED, blocked_by="Patient/p0")
    # Simulate an older database where the parent was loaded before wakeup triggers existed.
    store.db.execute("UPDATE records SET status='loaded' WHERE run_id=? AND rtype='Patient' AND source_key='p0'", (run,))
    assert store.work_queue(run, "Patient") == []
    assert store.release_ready_blocked(run) == 1
    assert [r["source_key"] for r in store.work_queue(run, "Patient")] == ["p1"]
