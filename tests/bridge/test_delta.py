import shutil
import sqlite3

from bridge.load.client import connect
from bridge.reconcile.answers import answer
from bridge.runs.delta import delta_summary
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore


def _mutate(src, dst):
    """Export B = A some weeks later: one deleted problem, one address change, one new visit."""
    shutil.copytree(src, dst)
    con = sqlite3.connect(dst / "halcyon.db")
    dx = con.execute("SELECT DX_ID FROM DX WHERE CODE_TYPE='10' AND CODE='I10' ORDER BY DX_ID LIMIT 1").fetchone()[0]
    con.execute("DELETE FROM DX WHERE DX_ID=?", (dx,))
    pat = con.execute("SELECT PAT_ID FROM PAT WHERE ADDR LIKE '%^%^%^%^%' ORDER BY PAT_ID LIMIT 1").fetchone()[0]
    con.execute("UPDATE PAT SET ADDR='1 NEW RD^^SPRINGFIELD^IL^62701' WHERE PAT_ID=?", (pat,))
    v = con.execute("SELECT * FROM VISIT WHERE PAT_ID=? AND VISIT_TYPE='OV' LIMIT 1", (pat,)).fetchone()
    cols = [c[1] for c in con.execute("PRAGMA table_info(VISIT)")]
    row = dict(zip(cols, v)) if v else {c: "" for c in cols}
    row.update(VISIT_ID="V9999999", PAT_ID=pat, VISIT_TYPE="OV", ADMIT_DT="202609150930", DISCH_DT="", STATUS="C",
               DEPT_ID=row.get("DEPT_ID") or "D200", ATTEND_PROV_ID=row.get("ATTEND_PROV_ID") or "PR001")
    con.execute(f"INSERT INTO VISIT ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    con.commit()
    return dx, pat


def _drive(store, runner, rid, choose=lambda q: q["options"][0]["key"]):
    for _ in range(40):
        blocking = [q for q in store.questions(rid, "open") if q["blocking"]]
        if store.run(rid)["status"] != "paused" and not blocking:
            return
        for q in blocking:
            o = next(o for o in q["options"] if o["key"] == choose(q))
            answer(store, q["id"], o["key"], value="2000-01-01" if o.get("needs_value") else None, answered_by="user:t")
        runner.resume(rid, "t", "user:t")


def test_cutover_delta(tmp_path, export_dir):
    target = f"embedded:{tmp_path / 'nimbus.db'}"
    store_a = RunStore(str(tmp_path / "a.db"))
    runner_a = Runner(store_a, connect(target))
    ra = runner_a.start(str(export_dir), target)
    _drive(store_a, runner_a, ra)

    dx, pat = _mutate(export_dir, tmp_path / "exportB")
    store_b = RunStore(str(tmp_path / "b.db"))
    client_b = connect(target)
    runner_b = Runner(store_b, client_b)
    rb = runner_b.start(str(tmp_path / "exportB"), target, prior_run_db=str(tmp_path / "a.db"))
    _drive(store_b, runner_b, rb)

    d = delta_summary(store_b, rb)["by_type"]
    assert d["Encounter"]["created"] == 1
    assert d["Patient"]["updated"] >= 1
    assert d["Condition"]["source_deleted"] == 1
    assert d["Encounter"]["unchanged"] > 100   # everything else is a no-op upsert
    # deletion surfaced as a question, defaulted to keep: still in Nimbus, unchanged
    q = next(q for q in store_b.questions(rb) if q["kind"] == "source_deleted" and q["match_key"] == "Condition")
    cond = client_b.search("Condition", sourceKey=dx)[0]
    assert cond["verificationStatus"] == "confirmed"
    # user decides to retire -> entered-in-error in Nimbus
    answer(store_b, q["id"], "retire", answered_by="user:t")
    runner_b.resume(rb, "retire deleted problems", "user:t")
    assert client_b.search("Condition", sourceKey=dx)[0]["verificationStatus"] == "entered-in-error"
    addr = client_b.search("Patient", sourceKey=store_b.xget(rb, "pat", pat))[0]["address"][0]
    assert addr["lines"] == ["1 NEW RD"]


def test_cutover_matches_mutator_delta(tmp_path, export_dir):
    """T-111: Bridge's delta run on export B reproduces exactly the changes the mutator recorded."""
    import json

    from testbed.halcyon.mutate import mutate

    target = f"embedded:{tmp_path / 'nimbus.db'}"
    store_a = RunStore(str(tmp_path / "a.db"))
    runner_a = Runner(store_a, connect(target))
    ra = runner_a.start(str(export_dir), target)
    _drive(store_a, runner_a, ra)

    mutate(export_dir, tmp_path / "exportB", seed=9)
    delta = json.loads((tmp_path / "exportB/answer_key/delta.json").read_text())["tables"]
    store_b = RunStore(str(tmp_path / "b.db"))
    runner_b = Runner(store_b, connect(target))
    rb = runner_b.start(str(tmp_path / "exportB"), target, prior_run_db=str(tmp_path / "a.db"))
    _drive(store_b, runner_b, rb)

    d = delta_summary(store_b, rb)["by_type"]
    n = lambda table, kind: len(delta.get(table, {}).get(kind, []))  # noqa: E731
    assert d["Encounter"].get("created", 0) == n("VISIT", "added")
    assert d.get("DocumentReference", {}).get("created", 0) == n("NOTE", "added")
    assert d["MedicationRequest"].get("updated", 0) == n("MED_ORD", "changed")
    assert d["Condition"].get("source_deleted", 0) == n("DX", "deleted")
    assert d["Appointment"].get("source_deleted", 0) == n("SCHED", "deleted")
    assert d["Patient"].get("created", 0) == n("PAT", "added")
    assert store_b.run(rb)["status"] in ("completed", "completed_with_exceptions")
