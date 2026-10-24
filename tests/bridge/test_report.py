from bridge.report import report_data, render_html, render_markdown
from bridge.runs.store import RunStore


def test_empty_report(env):
    store, _, _ = env
    rid = store.create_run("synthetic", "embedded::memory:", {"types": ["Patient"]})
    data = report_data(store, rid)
    assert data["summary"]["run_id"] == rid
    assert "Fidelity loss ledger" in render_html(data)
    assert "## Reconciliation questions" in render_markdown(data)


def test_escaping(env):
    store, _, _ = env
    rid = store.create_run("<script>alert(1)</script>", "embedded::memory:", {"types": ["Patient"]})
    store.add_alert(rid, rule="test", metric="count", severity="warning",
                    message='<img src=x onerror=alert(1)>')
    html = render_html(report_data(store, rid))
    assert "<script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html and "&lt;img" in html


def test_questions_and_metrics(env):
    store, _, _ = env
    rid = store.create_run("src", "embedded::memory:", {"types": ["Patient"]})
    store.upsert_question(rid, "identity", "P1", "Which?", [], True, {}, None)
    bid = store.create_batch(rid, "Patient", "nimbus-1")
    store.finish_batch(bid, "completed", {"loaded": 1}, {"attempted": 1, "loaded": 1})
    data = report_data(store, rid)
    assert data["question_counts"]["open"] == 1
    assert len(data["metrics"]) == 1
    assert "P1" in render_markdown(data)
    assert "nimbus-1" not in render_html(data)


def test_cli_report(env, tmp_path):
    store, _, _ = env
    rid = store.create_run("synthetic", "embedded::memory:", {"types": ["Patient"]})
    from bridge.__main__ import main
    path = tmp_path / "report.html"
    assert main(["--run-db", store.path, "--run-id", rid, "report", "--out", str(path)]) == 0
    assert path.read_text().startswith("<!doctype html>")
    md = tmp_path / "report.md"
    assert main(["--run-db", store.path, "--run-id", rid, "report", "--out", str(md)]) == 0
    assert md.read_text().startswith("# Bridge run report")
