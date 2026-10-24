from fastapi.testclient import TestClient

from bridge.web import create_app


def test_run_listing_and_pages(env):
    store, _, _ = env
    run = store.create_run("synthetic", "embedded::memory:", {"types": ["Patient"]})
    client = TestClient(create_app(store.path))
    assert client.get("/").status_code == 200
    assert run in client.get("/").text
    for page in ("", "/batches", "/alerts", "/questions", "/loss", "/lineage"):
        response = client.get(f"/runs/{run}{page}")
        assert response.status_code == 200, page
        assert "<!doctype html>" in response.text


def test_no_mutation_routes(env):
    store, _, _ = env
    run = store.create_run("synthetic", "embedded::memory:", {"types": ["Patient"]})
    client = TestClient(create_app(store.path))
    assert client.post(f"/runs/{run}/questions").status_code == 405
    assert client.get("/runs/does-not-exist").status_code == 404


def test_html_escaped(env):
    store, _, _ = env
    run = store.create_run("<script>alert(1)</script>", "embedded::memory:", {"types": ["Patient"]})
    store.add_alert(run, rule="drift", metric="hold", severity="warning", message="<img src=x>")
    client = TestClient(create_app(store.path))
    assert "<script>alert" not in client.get("/").text
    page = client.get(f"/runs/{run}/alerts").text
    assert "<img src=x>" not in page and "&lt;img src=x&gt;" in page


def test_lineage_query(env):
    store, _, _ = env
    run = store.create_run("synthetic", "embedded::memory:", {"types": ["Patient"]})
    store.stage(run, "Patient", [("PAT1", {"name": "Sample"}, {"source": "PAT"})])
    client = TestClient(create_app(store.path))
    page = client.get(f"/runs/{run}/lineage", params={"source_key": "PAT1"}).text
    assert "PAT1" in page and "pending" in page
