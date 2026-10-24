"""T-109: synthetic answer-key scoring, including real Bridge integration."""
import json

import pytest

from bridge.load.client import connect
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore
from testbed.halcyon.generator import generate
from testbed.scoring import main, render_markdown, score


@pytest.fixture
def env(tmp_path):
    # tests/bridge/conftest.py fixtures are scoped to tests/bridge only.
    store = RunStore(str(tmp_path / "run.db"))
    client = connect("embedded::memory:")
    return store, client, Runner(store, client)


def _key(tmp_path, persons, issues):
    export = tmp_path / "export"
    key = export / "answer_key"
    key.mkdir(parents=True)
    (key / "persons.json").write_text(json.dumps(persons))
    (key / "issues.jsonl").write_text("".join(json.dumps(i) + "\n" for i in issues))
    return export


def test_scoring_real_generated_export_and_bridge_run(tmp_path, env):
    """Exercise actual generation + staging + first conversion pass."""
    store, _, runner = env
    export = tmp_path / "generated"
    generate(export, seed=7, patients=40)
    rid = runner.start(str(export))
    report = score(export, store.path, rid)
    issues = [json.loads(line) for line in (export / "answer_key/issues.jsonl").read_text().splitlines()]
    assert set(report["issue_types"]) == {issue["type"] for issue in issues}
    assert report["overall"]["total"] == len(issues)
    assert sum(v["total"] for v in report["issue_types"].values()) == len(issues)
    assert report["overall"]["surfaced"] + report["overall"]["missed"] + report["overall"]["unmatched"] == len(issues)
    assert report["identity"]["patients"] == len({
        pat for ids in json.loads((export / "answer_key/persons.json").read_text()).values() for pat in ids
    })
    assert report["identity"]["missing_xrefs"] == 0
    assert "Pairwise precision" in render_markdown(report)


def test_issue_linkage_aliases_and_field_specific_vitals(tmp_path, env):
    store, _, _ = env
    export = _key(tmp_path, {"person": ["P1"]}, [
        {"type": "vital_problem", "table": "VITALS", "key": "V1", "field": "BP"},
        {"type": "feed_only_lab", "table": "LAB_RESULT", "key": "A1:GLU"},
        {"type": "registry_only", "table": "registry", "key": "M1:141:2026-01-02"},
        {"type": "duplicate_person", "table": "PAT", "key": "P1"},
    ])
    rid = store.create_run("src", "target", {"types": []})
    other = store.create_run("other", "target", {"types": []})
    store.stage(rid, "Observation", [
        ("VT-V1:WT", {}, {"table": "VITALS", "id": "V1", "column": "WT"}),
        ("VT-V1:BP", {}, {"table": "VITALS", "id": "V1", "column": "BP"}),
        ("LAB-A1:GLU", {}, {"channel": "hl7", "message": "M1"}),
    ])
    store.update_record(rid, "Observation", "VT-V1:WT", status="loaded",
                        annotations=[{"klass": "degraded"}])
    store.update_record(rid, "Observation", "LAB-A1:GLU", status="held")
    store.stage(rid, "Immunization", [
        ("REG-FAC1-M1-141-2026-01-02", {}, {"channel": "csv", "row": 2}),
    ])
    store.stage(rid, "Patient", [
        ("H-P1", {}, {"table": "PAT", "id": ["P1"]}),
    ])
    store.update_record(rid, "Patient", "H-P1", status="superseded")
    store.xset(rid, "pat", "P1", "H-P1")
    q = store.upsert_question(rid, "registry", "M1", "Review", [], False, {}, None)
    store.link_question(q["id"], "Immunization", "REG-FAC1-M1-141-2026-01-02", False)
    # A question in another run must not credit the current run's BP issue.
    q2 = store.upsert_question(other, "vital", "BP", "Review", [], False, {}, None)
    store.link_question(q2["id"], "Observation", "VT-V1:BP", False)

    report = score(export, store.path, rid)
    assert report["overall"] == {
        "total": 4, "surfaced": 3, "missed": 1, "unmatched": 0, "surfacing_rate": .75,
    }
    assert report["issue_types"]["vital_problem"]["missed_examples"] == ["VITALS/V1"]
    assert report["issue_types"]["feed_only_lab"]["surfaced"] == 1
    assert report["issue_types"]["registry_only"]["surfaced"] == 1
    assert report["issue_types"]["duplicate_person"]["surfaced"] == 1


def test_lossy_annotations_and_unmatched_are_distinct(tmp_path, env):
    store, _, _ = env
    export = _key(tmp_path, {}, [
        {"type": "lab", "table": "LAB_RESULT", "key": "RES1"},
        {"type": "absent", "table": "PROVIDER", "key": "PR404"},
    ])
    rid = store.create_run("src", "target", {"types": []})
    store.stage(rid, "Observation", [("LAB-A:K", {}, {"table": "LAB_RESULT", "id": "RES1"})])
    store.update_record(rid, "Observation", "LAB-A:K", status="loaded",
                        annotations=[{"klass": "inferred", "field": "unit"}])
    report = score(export, store.path, rid)
    assert report["issue_types"]["lab"]["surfaced"] == 1
    assert report["issue_types"]["absent"]["unmatched"] == 1
    assert report["overall"]["surfacing_rate"] == .5


def test_identity_pairwise_precision_recall(tmp_path, env):
    store, _, _ = env
    export = _key(tmp_path, {"A": ["P1", "P2", "P3"], "B": ["P4", "P5"]}, [])
    rid = store.create_run("src", "target", {"types": []})
    for pat, group in {"P1": "H1", "P2": "H1", "P3": "H2", "P4": "H2", "P5": "H3"}.items():
        store.xset(rid, "pat", pat, group)
    identity = score(export, store.path, rid)["identity"]
    assert identity["actual_positive_pairs"] == 4
    assert identity["predicted_positive_pairs"] == 2
    assert identity["true_positive_pairs"] == 1
    assert identity["pairwise_precision"] == .5
    assert identity["pairwise_recall"] == .25


def test_missing_xrefs_do_not_falsely_merge(tmp_path, env):
    store, _, _ = env
    export = _key(tmp_path, {"A": ["P1", "P2"], "B": ["P3"]}, [])
    rid = store.create_run("src", "target", {"types": []})
    store.xset(rid, "pat", "P1", "H1")
    identity = score(export, store.path, rid)["identity"]
    assert identity["missing_xrefs"] == 2
    assert identity["predicted_positive_pairs"] == 0
    assert identity["pairwise_precision"] == 1.0
    assert identity["pairwise_recall"] == 0.0


def test_cli_writes_json_and_markdown(tmp_path, env, capsys):
    store, _, _ = env
    export = _key(tmp_path, {"A": ["P1"]}, [
        {"type": "missed", "table": "PAT", "key": "P1"},
    ])
    rid = store.create_run("src", "target", {"types": []})
    json_out, md_out = tmp_path / "score.json", tmp_path / "score.md"
    assert main(["--export", str(export), "--run-db", store.path, "--run-id", rid,
                 "--json-out", str(json_out), "--md-out", str(md_out)]) == 0
    report = json.loads(json_out.read_text())
    assert report["issue_types"]["missed"]["unmatched"] == 1
    assert "| **Total** |" in md_out.read_text()
    assert '"run_id"' in capsys.readouterr().out


def test_unknown_run_and_missing_db_fail(tmp_path, env):
    store, _, _ = env
    export = _key(tmp_path, {}, [])
    with pytest.raises(ValueError, match="not found"):
        score(export, store.path)
    with pytest.raises(Exception):
        score(export, tmp_path / "nonexistent.db")
    assert not (tmp_path / "nonexistent.db").exists()


def test_duplicate_ground_truth_pat_ids_rejected(tmp_path, env):
    store, _, _ = env
    export = _key(tmp_path, {"A": ["P1"], "B": ["P1"]}, [])
    rid = store.create_run("src", "target", {"types": []})
    with pytest.raises(ValueError, match="multiple answer-key persons"):
        score(export, store.path, rid)
