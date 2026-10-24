import json

from bridge.compare import compare, run_profile
from bridge.load.client import connect
from bridge.reconcile.rules_io import export_rules, load_rules
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore


def test_second_rehearsal_reuses_answers(env, export_dir, drive, tmp_path):
    store1, client1, runner1 = env
    r1 = runner1.start(str(export_dir))
    drive(store1, runner1, r1)
    answered = store1.questions(r1, "answered")
    assert answered

    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps(export_rules(store1, r1)))
    rules = load_rules(str(rules_file))
    assert len(rules) == len(store1.rules(r1))

    store2 = RunStore(str(tmp_path / "rehearsal2.db"))
    client2 = connect("embedded::memory:")
    runner2 = Runner(store2, client2)
    r2 = runner2.start(str(export_dir), rules=rules)

    # nothing that was answered in rehearsal 1 is asked again
    asked2 = {(q["kind"], q["match_key"]) for q in store2.questions(r2, None)}
    assert not asked2 & {(q["kind"], q["match_key"]) for q in answered}
    assert not [q for q in store2.questions(r2, "open") if q["blocking"]]
    assert store2.run(r2)["status"] in ("completed", "completed_with_exceptions")
    # same outcome in the target
    for rtype in store1.run(r1)["config"]["types"]:
        assert client2.count(rtype)["total"] == client1.count(rtype)["total"], rtype

    cmp = compare(run_profile(store1, r1), run_profile(store2, r2))
    assert cmp["summary"]["pauses"]["b"] < cmp["summary"]["pauses"]["a"]
    assert cmp["summary"]["rules_imported"]["b"] == len(rules)


def test_load_rules_directly_from_run_db(env, export_dir, drive, tmp_path):
    store1, _, runner1 = env
    r1 = runner1.start(str(export_dir))
    drive(store1, runner1, r1)
    assert load_rules(store1.path)[0]["source_run"] == r1
