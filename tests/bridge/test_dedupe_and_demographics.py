"""Merged charts: newest demographics win. Duplicates: the earliest record wins, whatever the batch timing."""
from bridge.load.client import connect
from bridge.mapping.core import _newest
from bridge.reconcile.answers import answer
from bridge.runs.runner import Runner
from bridge.runs.store import BLOCKED, DROPPED, LOADED, PENDING, REJECTED, RunStore
from testbed.halcyon.generator import generate
from testbed.simulated_user import SimulatedAnalyst


def _chart(pat, last_upd, addr="1 OLD ST^^TOWN^IL^60000", phone="(312) 555-0101"):
    return {"PAT_ID": pat, "LAST_UPD": last_upd, "ADDR": addr, "PHONE_HOME": phone}


def test_newest_demographics_across_merged_charts():
    primary, other = _chart("P1", "20210101"), _chart("P2", "20190101", phone="(312) 555-0202")
    src = {"members": [primary, other], "a08": {"P2": {"at": "202203011000", "addr": "9 NEW AVE^^CITY^IL^60001",
                                                       "phone": "(696) 709-9870"}}}
    assert _newest(src, primary, "PHONE_HOME", "phone") == ("(696) 709-9870", "a08:P2")
    assert _newest(src, primary, "ADDR", "addr", empty="^") == ("9 NEW AVE^^CITY^IL^60001", "a08:P2")
    # The merged chart's A08 predates the primary's own last update: the primary's value is newer.
    src["a08"]["P2"]["at"] = "202001011000"
    assert _newest(src, primary, "PHONE_HOME", "phone") == ("(312) 555-0101", None)
    # A merged chart's own row that is newer than the primary's wins too.
    other["LAST_UPD"] = "20230101"
    assert _newest(src, primary, "PHONE_HOME", "phone") == ("(312) 555-0202", "chart:P2")


def test_unmerged_patient_keeps_previous_rule():
    primary = _chart("P1", "20210101")
    assert _newest({"members": [primary], "a08": {}}, primary, "ADDR", "addr", empty="^") == (primary["ADDR"], None)
    src = {"members": [primary], "a08": {"P1": {"at": "202201011000", "addr": "^^^^", "phone": "(696) 709-9870"}}}
    assert _newest(src, primary, "ADDR", "addr", empty="^") == (primary["ADDR"], None)  # blank A08 address ignored
    assert _newest(src, primary, "PHONE_HOME", "phone") == ("(696) 709-9870", "a08:P1")


def test_dropped_or_rejected_record_releases_same_type_waiters(tmp_path):
    store = RunStore(str(tmp_path / "run.db"))
    run = store.create_run("s", "n", {})
    store.stage(run, "Condition", [("D1", {}, {}), ("D2", {}, {}), ("D3", {}, {})])
    store.stage(run, "Observation", [("O1", {}, {})])
    for key, parent in (("D2", "Condition/D1"), ("D3", "Condition/D2")):
        store.update_record(run, "Condition", key, status=BLOCKED, blocked_by=parent)
    store.update_record(run, "Observation", "O1", status=BLOCKED, blocked_by="Condition/D1")
    store.update_record(run, "Condition", "D1", status=DROPPED)
    assert store.status_of(run, "Condition", "D2") == PENDING
    assert store.status_of(run, "Observation", "O1") == BLOCKED  # other types still need a loaded parent
    store.update_records(run, "Condition", [("D2", {"status": REJECTED})])
    assert store.status_of(run, "Condition", "D3") == PENDING
    store.update_record(run, "Condition", "D3", status=LOADED)


def _convert(tmp_path, batch_size):
    export = tmp_path / "export"
    if not export.exists():
        generate(export, seed=42, patients=300)
    store = RunStore(str(tmp_path / f"run{batch_size}.db"))
    runner = Runner(store, connect("embedded::memory:"))
    rid = runner.start(str(export), batch_size=batch_size)
    analyst = SimulatedAnalyst(export)
    for _ in range(60):
        blocking = [q for q in store.questions(rid) if q["blocking"]]
        if store.run(rid)["status"] != "paused" and not blocking:
            break
        for q in blocking:
            detail = store.question(q["id"])
            linked = detail["affected"]
            rec = store.record(rid, linked[0]["rtype"], linked[0]["source_key"]) if linked else None
            option, value, why = analyst.choose(detail, rec["source"] if rec else None)
            answer(store, q["id"], option, value, analyst.name, why)
        runner.resume(rid, "test", analyst.name)
    assert store.run(rid)["status"] == "completed"
    return {(r[0], r[1]): (r[2], r[3]) for r in store.db.execute(
        "SELECT rtype, source_key, status, note FROM records WHERE run_id=? AND rtype IN "
        "('Condition','AllergyIntolerance','Immunization')", (rid,))}


def test_duplicate_winner_does_not_depend_on_batch_size(tmp_path):
    small, large = _convert(tmp_path, 50), _convert(tmp_path, 500)
    assert {k: v[0] for k, v in small.items()} == {k: v[0] for k, v in large.items()}
    # The same record survives each duplicate group in both runs.
    sup = {k: v[1] for k, v in small.items() if v[0] == "superseded"}
    assert sup and sup == {k: v[1] for k, v in large.items() if v[0] == "superseded"}
