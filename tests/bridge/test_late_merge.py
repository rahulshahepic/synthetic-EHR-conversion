from bridge.assistant import BridgeAssistant
from bridge.runs.revert import revert


def _loaded_pair_answered_different(a):
    """Drive a run answering identity questions 'different', return one such (survivor, duplicate) pair."""
    pair = None
    for _ in range(30):
        qs = a.list_questions(blocking_only=True)["questions"]
        if not qs and a.run_status()["status"] != "paused":
            break
        for q in qs:
            opt = "different" if q["kind"] == "identity_match" else q["options"][0]["key"]
            if q["kind"] == "identity_match" and pair is None:
                ctx = a.get_question(q["id"])["context"]
                pair = (ctx["candidate_patient"], ctx["this_patient"])
            needs = next(o for o in q["options"] if o["key"] == opt).get("needs_value")
            a.answer_question(q["id"], opt, "user:alice", value="2000-01-01" if needs else None)
        a.resume_run("go", "user:alice")
    return pair


def test_late_merge_and_revert(tmp_path, export_dir):
    a = BridgeAssistant(str(tmp_path / "run.db"))
    a.start_run(str(export_dir), target="embedded::memory:")
    surv, dup = _loaded_pair_answered_different(a)
    store, client = a.store, a.runner().client
    rid = store.run()["id"]
    s_id, d_id = store.record(rid, "Patient", surv)["target_id"], store.record(rid, "Patient", dup)["target_id"]
    dup_encounters = len(client.search("Encounter", patient=d_id, limit=1000))
    assert dup_encounters > 0
    before_active = client.count("Patient")["active"]

    assert "error" in a.merge_patients(surv, dup, "assistant")
    res = a.merge_patients(surv, dup, "user:alice")
    assert "error" not in res, res
    assert client.count("Patient")["active"] == before_active - 1
    assert len(client.search("Encounter", patient=d_id, limit=1000)) == 0
    assert len(client.search("Encounter", patient=s_id, limit=1000)) >= dup_encounters
    assert store.status_of(rid, "Patient", dup) == "superseded"
    pat_id = store.record(rid, "Patient", dup)["source"]["members"][0]["PAT_ID"]
    assert store.xget(rid, "pat", pat_id) == surv

    revert(store, client, rid, "batch", res["batch"], by="user:alice")
    assert client.count("Patient")["active"] == before_active
    assert len(client.search("Encounter", patient=d_id, limit=1000)) == dup_encounters
    assert store.status_of(rid, "Patient", dup) == "loaded"
    assert store.xget(rid, "pat", pat_id) == dup
