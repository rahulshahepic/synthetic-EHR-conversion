from bridge.readiness import readiness, signoff


def test_no_go_until_signed_off_then_go(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    paused_once = readiness(store, client, rid)
    assert paused_once["decision"] == "NO-GO" and "run_finished" in paused_once["reasons"]

    drive(store, runner, rid)
    r = readiness(store, client, rid)
    assert r["decision"] == "NO-GO"
    assert r["reasons"] == ["fidelity_loss_signed_off"]
    missing = next(c for c in r["checks"] if c["check"] == "fidelity_loss_signed_off")["detail"]["missing"]
    assert "Observation" in missing

    for domain in missing:
        signoff(store, rid, domain, "user:domain-owner", "reviewed loss report")
    r = readiness(store, client, rid)
    assert r["decision"] == "GO", r["reasons"]


def test_signoff_requires_named_user_and_goes_stale(env, export_dir, drive):
    store, client, runner = env
    rid = runner.start(str(export_dir))
    drive(store, runner, rid)
    import pytest
    with pytest.raises(ValueError):
        signoff(store, rid, "Observation", "assistant")
    signoff(store, rid, "Observation", "user:x")
    store.xset(rid, "signoff", "Observation", {**store.xget(rid, "signoff", "Observation"), "loss_records": -1})
    detail = next(c for c in readiness(store, client, rid)["checks"] if c["check"] == "fidelity_loss_signed_off")["detail"]
    assert "Observation" in detail["stale"]
