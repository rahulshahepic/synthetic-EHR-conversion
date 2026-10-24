"""Regression guards for SQL access paths that otherwise grow quadratically at 50k patients."""
from bridge.runs.store import RunStore
from nimbus.service import NimbusService


def _plan(db, sql, args=()):
    return " ".join(row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql, args))


def test_patient_identifier_cleanup_uses_patient_id_index():
    service = NimbusService(":memory:")
    plan = _plan(service._db, "DELETE FROM identifiers WHERE patient_id=?", ("test",))
    assert "ix_ident_patient" in plan, plan


def test_nimbus_batch_sequence_uses_index():
    service = NimbusService(":memory:")
    plan = _plan(service._db, "SELECT COALESCE(MAX(seq), 0) + 1 FROM batches")
    assert "ix_nimbus_batches_seq" in plan, plan


def test_nimbus_paginated_reads_use_ordered_index():
    service = NimbusService(":memory:")
    plan = _plan(service._db, "SELECT r.* FROM resources r WHERE r.rtype=? ORDER BY r.created_at, r.id LIMIT ? OFFSET ?", ("Patient", 1000, 0))
    assert "ix_resources_rtype_created_id" in plan, plan
    assert "USE TEMP B-TREE FOR ORDER BY" not in plan, plan


def test_bridge_batch_sequence_uses_index():
    store = RunStore(":memory:")
    plan = _plan(store.db, "SELECT COALESCE(MAX(seq),0)+1 FROM batches WHERE run_id=?", ("test",))
    assert "ix_bridge_batches_run_seq" in plan, plan


def test_staging_streams_generator_and_preserves_sequence_and_replacement():
    store = RunStore(":memory:")
    run = store.create_run("synthetic", "nimbus", {"types": ["Patient"]})
    consumed = []

    def rows():
        for i in range(12):
            consumed.append(i)
            yield str(i), {"i": i}, {"origin": "fixture"}

    assert store.stage(run, "Patient", rows()) == 12
    assert consumed == list(range(12))
    assert [r["source_key"] for r in store.work_queue(run, "Patient")] == [str(i) for i in range(12)]
    assert store.stage(run, "Patient", iter([("3", {"i": 300}, {"origin": "replacement"})])) == 1
    assert store.record(run, "Patient", "3")["source"]["i"] == 300


def test_nimbus_keyset_reads_use_ordered_index():
    service = NimbusService(":memory:")
    plan = _plan(
        service._db,
        "SELECT r.* FROM resources r WHERE r.rtype=? AND (r.created_at, r.id) > (?, ?)"
        " ORDER BY r.created_at, r.id LIMIT ? OFFSET ?",
        ("Patient", "2020-01-01", "some-id", 1000, 0),
    )
    assert "ix_resources_rtype_created_id" in plan, plan
    assert "USE TEMP B-TREE FOR ORDER BY" not in plan, plan
