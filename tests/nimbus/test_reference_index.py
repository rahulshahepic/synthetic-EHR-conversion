from nimbus.service import NimbusService


def test_reference_conflict_index(tmp_path):
    service = NimbusService(str(tmp_path / "nimbus.db"))
    indexes = {row[1] for row in service._db.execute("PRAGMA index_list(refs)")}
    assert "ix_refs_owner_target" in indexes
    plan = [row[3] for row in service._db.execute(
        "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM refs WHERE owner_rtype=? AND target_id=?",
        ("AllergyIntolerance", "patient-1"))]
    assert any("ix_refs_owner_target" in row for row in plan), plan
    plan = [row[3] for row in service._db.execute(
        """EXPLAIN QUERY PLAN SELECT r.id, r.data FROM refs f
        JOIN resources r ON r.rtype=f.owner_rtype AND r.id=f.owner_id
        WHERE f.owner_rtype='Coverage' AND f.field='patient' AND f.target_id=?""",
        ("patient-1",))]
    assert any("ix_refs_owner_target" in row for row in plan), plan
