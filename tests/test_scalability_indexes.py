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
