import json

import pytest

from bridge.mapping import base
from bridge.reconcile.answers import AnswerError, answer
from bridge.runs.revert import RevertBlocked, revert
from bridge.status import explain, run_summary


def nimbus_counts(client, types):
    return {t: client.count(t)["total"] for t in types}


def test_first_pause_is_shared_department_question(env, export_dir):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    run = store.run(rid)
    assert run["status"] == "paused" and "hold_rate" in store.alerts(rid, "open")[0]["rule"]
    qs = store.questions(rid)
    assert {q["kind"] for q in qs} == {"shared_department"}
    assert all(q["blocking"] and q["affected_count"] == 3 for q in qs)


def test_full_run_reconciles_with_nimbus(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    assert drive(store, runner, rid) == "completed"
    summary = run_summary(store, rid)
    for rtype, info in summary["by_type"].items():
        loaded = info["counts"].get("loaded", 0)
        assert client.count(rtype)["total"] == loaded, rtype
        assert set(info["counts"]) <= {"loaded", "dropped", "superseded"}, (rtype, info["counts"])
    # identity: answering every match "same" yields exactly the true number of people
    persons = json.loads((export_dir / "answer_key/persons.json").read_text())
    assert client.count("Patient")["total"] == len(persons)
    assert summary["by_type"]["Patient"]["fidelity_mean"] > 0.85


def test_identity_question_different_keeps_both(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    drive(store, runner, rid, choose=lambda q: "different" if q["kind"] == "identity_match" else q["options"][0]["key"])
    persons = json.loads((export_dir / "answer_key/persons.json").read_text())
    n_identity_q = len(store.questions(rid, "answered", "identity_match"))
    assert n_identity_q > 0
    assert client.count("Patient")["total"] == len(persons) + n_identity_q


def test_grouped_answer_releases_many_records(env, export_dir):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    for q in store.questions(rid):
        answer(store, q["id"], "duplicate", answered_by="user:test")
    runner.resume(rid, "t", "user:test")
    q = next((q for q in store.questions(rid) if q["kind"] == "unknown_visit_type"), None)
    assert q is not None and q["affected_count"] >= 2
    res = answer(store, q["id"], "ambulatory", answered_by="user:test")
    assert res["released"] == q["affected_count"]


def test_forced_breach_pauses_with_samples(env, export_dir, monkeypatch):
    store, client, runner = env
    original = base.MAPPERS["Encounter"]

    def broken(ctx):
        out = original(ctx)
        if out and ctx.src["VISIT_ID"].endswith(("3", "7")):
            out.pop("class")
        return out

    monkeypatch.setitem(base.MAPPERS, "Encounter", broken)
    rid = runner.start(str(export_dir))
    for _ in range(10):
        if any(a["rule"] == "reject_rate" for a in store.alerts(rid)):
            break
        for q in store.questions(rid):
            if q["blocking"]:
                answer(store, q["id"], q["options"][0]["key"], value="2000-01-01", answered_by="user:test")
        runner.resume(rid, "t", "user:test")
    alert = next(a for a in store.alerts(rid) if a["rule"] == "reject_rate")
    assert alert["rtype"] == "Encounter" and alert["severity"] == "pause"
    assert alert["samples"][0]["issue"]["code"] == "E_REQUIRED"
    assert store.run(rid)["status"] == "paused"


def test_revert_type_then_run(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    drive(store, runner, rid)
    types = store.run(rid)["config"]["types"]
    before = nimbus_counts(client, types)
    res = revert(store, client, rid, "type", "AllergyIntolerance")
    after = nimbus_counts(client, types)
    assert after["AllergyIntolerance"] == 0
    assert {t: v for t, v in after.items() if t != "AllergyIntolerance"} == {t: v for t, v in before.items() if t != "AllergyIntolerance"}
    assert res["reverted_batches"]
    # resume reloads them
    runner.resume(rid, "reload", "user:test")
    assert nimbus_counts(client, types) == before
    revert(store, client, rid, "run", cascade=True)
    assert all(v == 0 for v in nimbus_counts(client, types).values())
    assert store.run(rid)["status"] == "reverted"


def test_revert_batch_with_dependents_requires_cascade(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    drive(store, runner, rid)
    first_patient_batch = store.batches(rid, "Patient", "loaded")[0]["id"]
    with pytest.raises(RevertBlocked) as exc:
        revert(store, client, rid, "batch", first_patient_batch)
    assert exc.value.blocking


def test_answer_guards(env, export_dir):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    q = store.questions(rid)[0]
    with pytest.raises(AnswerError):
        answer(store, q["id"], "nonsense")
    with pytest.raises(AnswerError):
        answer(store, q["id"], "duplicate", answered_by="assistant")
    answer(store, q["id"], "duplicate", answered_by="user:test")
    with pytest.raises(AnswerError):
        answer(store, q["id"], "duplicate", answered_by="user:test")


def test_explain_shows_lineage_and_fidelity(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    drive(store, runner, rid)
    rec = store.records_by_status(rid, "loaded", "Condition", limit=1)[0]
    ex = explain(store, rid, rec["source_key"], "Condition")[0]
    assert ex["lineage"]["table"] == "DX" and ex["nimbus_id"] and ex["annotations"]
    assert client.get("Condition", ex["nimbus_id"])["sourceKey"] == rec["source_key"]
