from bridge.mapping import base
from bridge.reconcile.answers import answer
from bridge.verify import _nimbus_all, _same, verify_run


def test_same_compares_refs_by_source_key_and_ignores_nimbus_additions():
    assert _same({"patient": {"sourceKey": "Patient/H-1"}, "x": 1.0},
                 {"patient": {"id": "uuid", "sourceKey": "Patient/H-1"}, "x": 1, "extra": True})
    assert not _same({"patient": {"sourceKey": "Patient/H-1"}}, {"patient": {"id": "u", "sourceKey": "Patient/H-2"}})
    assert not _same({"codes": [1, 2]}, {"codes": [1]})


def test_clean_run_verifies(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    assert drive(store, runner, rid) in ("completed", "completed_with_exceptions")
    report = verify_run(store, client, rid)
    assert report["ok"], report
    assert report["readback"]["sampled"] > 100
    import json
    kinds = {row[0] for row in store.db.execute(
        "SELECT kind FROM events WHERE run_id=? AND kind IN ('staging_timing', 'verification_timing')", (rid,)
    )}
    assert kinds == {"staging_timing", "verification_timing"}
    measured = [json.loads(row[0]).get("timings", {}) for row in store.db.execute(
        "SELECT metrics FROM batches WHERE run_id=? AND metrics IS NOT NULL", (rid,)
    )]
    assert any("map_seconds" in t and "target_submit_seconds" in t for t in measured)



def test_sentinel_catches_silently_inactivated_anticoagulants(env, export_dir, monkeypatch):
    store, client, runner = env
    original = base.MAPPERS["MedicationRequest"]

    def bug(ctx):
        out = original(ctx)
        if out and ctx.src["FORM_CODE"] in ("HFORM0004", "HFORM0011"):
            out["status"] = "completed"  # a mapping bug that loses clinical meaning but passes Nimbus validation
        return out

    monkeypatch.setitem(base.MAPPERS, "MedicationRequest", bug)
    rid = runner.start(str(export_dir))
    for _ in range(30):
        if any(a["rule"] == "clinical_sentinel" for a in store.alerts(rid)):
            break
        for q in store.questions(rid, "open"):
            if q["blocking"]:
                o = q["options"][0]
                answer(store, q["id"], o["key"], value="2000-01-01" if o.get("needs_value") else None, answered_by="user:t")
        runner.resume(rid, "t", "user:t")
    alert = next(a for a in store.alerts(rid) if a["rule"] == "clinical_sentinel")
    assert alert["metric"] == "active_anticoagulants"
    assert store.run(rid)["status"] == "paused"


def test_nimbus_sentinel_scan_streams_pages_without_collecting_all_records():
    class FakeClient:
        def __init__(self):
            self.started = False

        def iter_search(self, rtype):
            assert rtype == "Observation"
            self.started = True
            for i in range(1002):
                yield {"id": str(i)}

    client = FakeClient()
    records = _nimbus_all(client, "Observation")
    assert not client.started
    assert next(records)["id"] == "0"
    assert client.started
    assert len(list(records)) == 1001


def test_sentinel_counts_streamed_units_and_statuses():
    from bridge.verify import _sentinel
    from bridge.runs.store import LOADED, HELD, DROPPED
    rows = [
        {"source_key": "A1", "status": LOADED, "patient": "P1"},
        {"source_key": "A2", "status": LOADED, "patient": "P1"},
        {"source_key": "A3", "status": HELD, "patient": "P2"},
        {"source_key": "A4", "status": DROPPED, "patient": "P3"},
    ]
    out = _sentinel("allergies", "patients with allergies", iter(rows),
                    lambda r: True, 1, unit=lambda r: r["patient"])
    assert out["ok"]
    assert out["source"] == 3
    assert out["expected_in_nimbus"] == 1
    assert out["not_loaded_by_status"] == {HELD: 1, DROPPED: 1}
    assert out["not_loaded_examples"] == ["A3", "A4"]
