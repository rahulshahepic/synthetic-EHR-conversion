"""Onboarding a second source system (Muse's Lakeside profile, T-108) without code changes:
unknown facilities become questions, metric lab units are kept, nothing is silently dropped."""
import pytest

from bridge.assistant import BridgeAssistant
from bridge.mapping import base
from testbed.halcyon.generator import generate
from testbed.simulated_user import SimulatedAnalyst


@pytest.fixture(scope="module")
def lakeside(tmp_path_factory):
    out = tmp_path_factory.mktemp("lakeside")
    generate(out / "export", seed=3, patients=80, profile="lakeside")
    a = BridgeAssistant(str(out / "run.db"))
    a.start_run(str(out / "export"), target="embedded::memory:")
    an = SimulatedAnalyst(out / "export")
    kinds = set()
    for _ in range(40):
        qs = a.list_questions(blocking_only=True, limit=500)["questions"]
        if a.run_status()["status"] != "paused" and not qs:
            break
        for q in qs:
            kinds.add(q["kind"])
            d = a.get_question(q["id"])
            opt, val, why = an.choose(d, d["examples"][0]["source"] if d["examples"] else None)
            assert "error" not in a.answer_question(q["id"], opt, an.name, value=val, rationale=why)
        a.resume_run("analyst answered", an.name)
    return a, kinds


def test_unknown_facilities_become_questions(lakeside):
    a, kinds = lakeside
    assert {"facility_timezone", "facility_vital_units"} <= kinds
    rules = {(r["kind"], r["match_key"]): r["decision"]["option"] for r in a.list_rules()}
    assert rules[("facility_timezone", "FAC9")] == "America/Denver"
    assert rules[("facility_vital_units", "FAC9")] == "metric"


def test_lakeside_converts_cleanly(lakeside):
    a, _ = lakeside
    st = a.run_status()
    assert st["status"] in ("completed", "completed_with_exceptions")
    obs = st["by_type"]["Observation"]["counts"]
    assert obs.get("dropped", 0) / sum(obs.values()) < 0.02
    assert a.verify_run()["ok"]
    client = a.runner().client
    enc = client.search("Encounter", limit=5)
    assert all(e["period"]["start"].endswith(("-06:00", "-07:00")) for e in enc)  # Mountain time, not Chicago


def test_metric_lab_units_kept_as_reported(lakeside):
    a, _ = lakeside
    rows = a.store.db.execute(
        "SELECT mapped FROM records WHERE rtype='Observation' AND status='loaded' "
        "AND json_extract(source, '$.TEST_CODE')='GLU' AND json_extract(mapped, '$.valueQuantity') IS NOT NULL LIMIT 20").fetchall()
    assert rows
    import json
    assert {json.loads(r[0])["valueQuantity"]["unit"] for r in rows} == {"mmol/L"}


def test_drop_rate_monitor_pauses_on_mass_drops(env, export_dir, monkeypatch):
    store, client, runner = env
    original = base.MAPPERS["Immunization"]

    def drop_half(ctx):
        if ctx.key.endswith(("1", "3", "5", "7", "9")):
            ctx.note("record", "dropped", 1.0, "bug: dropped")
            return None
        return original(ctx)

    monkeypatch.setitem(base.MAPPERS, "Immunization", drop_half)
    rid = runner.start(str(export_dir))
    from bridge.reconcile.answers import answer
    for _ in range(30):
        if any(al["rule"] == "drop_rate" for al in store.alerts(rid)):
            break
        for q in store.questions(rid, "open"):
            if q["blocking"]:
                o = q["options"][0]
                answer(store, q["id"], o["key"], value="2000-01-01" if o.get("needs_value") else None, answered_by="user:t")
        runner.resume(rid, "t", "user:t")
    al = next(al for al in store.alerts(rid) if al["rule"] == "drop_rate")
    assert al["rtype"] == "Immunization" and al["samples"][0]["reason"] == "bug: dropped"
