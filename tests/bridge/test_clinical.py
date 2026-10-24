import json

import pytest

from bridge.load.client import connect
from bridge.normalize.sig import parse_sig
from bridge.reconcile.answers import answer
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore


@pytest.fixture(scope="module")
def run(tmp_path_factory, export_dir):
    store = RunStore(str(tmp_path_factory.mktemp("clin") / "run.db"))
    client = connect("embedded::memory:")
    runner = Runner(store, client)
    rid = runner.start(str(export_dir))
    for _ in range(50):
        open_blocking = [q for q in store.questions(rid, "open") if q["blocking"]]
        if store.run(rid)["status"] != "paused" and not open_blocking:
            break
        for q in open_blocking:
            opt = q["options"][0]
            answer(store, q["id"], opt["key"], value="12345" if opt.get("needs_value") else None, answered_by="user:test")
        runner.resume(rid, "t", "user:test")
    return store, client, rid, export_dir


def issues(export_dir, kind):
    return [json.loads(l) for l in (export_dir / "answer_key/issues.jsonl").read_text().splitlines()
            if json.loads(l)["type"] == kind]


def loaded(store, rid, rtype, key):
    rec = store.record(rid, rtype, key)
    assert rec is not None, key
    return rec


def test_all_types_loaded_and_reconciled(run):
    store, client, rid, _ = run
    counts = store.status_counts(rid)
    for rtype in store.run(rid)["config"]["types"]:
        assert client.count(rtype)["total"] == counts.get(rtype, {}).get("loaded", 0), rtype
        assert counts[rtype].get("loaded", 0) > 0, rtype


def test_feed_only_and_corrected_labs(run):
    store, client, rid, export_dir = run
    feed_only = issues(export_dir, "feed_only_lab")
    assert feed_only
    rec = loaded(store, rid, "Observation", f"LAB-{feed_only[0]['key']}")
    assert rec["lineage"]["channel"] == "hl7"
    for c in issues(export_dir, "oru_corrected_result"):
        lab = store.db.execute("SELECT source_key FROM records WHERE run_id=? AND rtype='Observation' AND json_extract(lineage,'$.id')=?",
                               (rid, c["key"])).fetchone()
        rec = store.record(rid, "Observation", lab[0])
        if rec["status"] == "loaded" and "valueQuantity" in rec["mapped"]:
            assert rec["mapped"]["status"] == "corrected"
            assert rec["mapped"]["valueQuantity"]["value"] == float(c["corrected_value"])


def test_siu_cancellation_wins(run):
    store, client, rid, export_dir = run
    for i in issues(export_dir, "siu_newer_status"):
        rec = loaded(store, rid, "Appointment", i["key"])
        assert rec["mapped"]["status"] == "cancelled"


def test_registry_only_immunizations_added(run):
    store, client, rid, export_dir = run
    n = store.db.execute("SELECT COUNT(*) FROM records WHERE run_id=? AND rtype='Immunization' AND source_key LIKE 'REG-%' "
                         "AND status='loaded'", (rid,)).fetchone()[0]
    assert n >= len(issues(export_dir, "registry_only_immunization")) * 0.8


def test_not_a_vaccine_dropped_and_generic_users_dropped(run):
    store, client, rid, export_dir = run
    for i in issues(export_dir, "not_a_vaccine"):
        assert store.status_of(rid, "Immunization", i["key"]) == "dropped"
    for i in issues(export_dir, "generic_user"):
        assert store.status_of(rid, "UserAccount", i["key"]) == "dropped"


def test_truncated_notes_flagged(run):
    store, client, rid, export_dir = run
    for i in issues(export_dir, "truncated_note"):
        rec = loaded(store, rid, "DocumentReference", i["key"])
        assert "truncated at 65,535" in rec["mapped"]["content"]
        assert any(a["klass"] == "degraded" and a["field"] == "content" for a in rec["annotations"])


def test_charge_amount_eras(run):
    store, client, rid, _ = run
    rows = store.db.execute("SELECT source, mapped FROM records WHERE run_id=? AND rtype='ChargeItem' AND status='loaded'", (rid,))
    for src, mapped in rows:
        src, mapped = json.loads(src), json.loads(mapped)
        expected = float(src["AMOUNT"]) if src["POST_DT"] < "20120101" else int(src["AMOUNT"]) / 100
        assert mapped["amount"] == round(expected, 2)


def test_implausible_vitals_never_reach_nimbus(run):
    store, client, rid, _ = run
    rejected = store.records_by_status(rid, "rejected", "Observation")
    assert not [r for r in rejected if any(i["code"] == "E_PLAUSIBILITY" for i in r["issues"] or [])]


@pytest.mark.parametrize("sig,dose,unit,route,count,prn", [
    ("1 tab po daily", 1, "{tab}", "oral", 1, False),
    ("take one tablet by mouth once daily", 1, "{tab}", "oral", 1, False),
    ("2 puffs inh q4-6h prn sob", 2, "{puff}", "inhaled", 1, True),
    ("1/2 tab po qhs", 0.5, "{tab}", "oral", 1, False),
    ("10 units subq qhs", 10, "[iU]", "subcut", 1, False),
    ("1 CAP PO TID X 10 DAYS", 1, "{cap}", "oral", 3, False),
])
def test_sig_v0(sig, dose, unit, route, count, prn):
    r = parse_sig(sig)
    assert (r.dose_value, r.dose_unit, r.route, r.frequency_count, r.as_needed) == (dose, unit, route, count, prn)


def test_sig_low_confidence():
    assert parse_sig("ud per INR clinic").confidence < 0.5
    assert parse_sig("1-2 tabs po q6h prn pain").confidence < 0.8


def test_no_reference_lost_to_a_temporarily_held_parent(run):
    """Records whose parent was waiting on a question must wait too, not drop the link (regression)."""
    store, client, rid, _ = run
    lost = store.db.execute(
        "SELECT rtype, source_key, field, note FROM loss WHERE run_id=? AND klass='dropped' AND "
        "(note LIKE '%(held)%' OR note LIKE '%(pending)%' OR note LIKE '%(blocked)%')", (rid,)).fetchall()
    assert not lost, [tuple(r) for r in lost[:5]]
