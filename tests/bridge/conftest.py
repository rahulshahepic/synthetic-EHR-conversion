import pytest

from bridge.load.client import connect
from bridge.reconcile.answers import answer
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore
from testbed.halcyon.generator import generate


@pytest.fixture(scope="session")
def export_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("halcyon")
    generate(out, seed=11, patients=150)
    return out


@pytest.fixture
def env(tmp_path):
    store = RunStore(str(tmp_path / "run.db"))
    client = connect("embedded::memory:")
    return store, client, Runner(store, client)


@pytest.fixture
def drive():
    return _drive


def _drive(store, runner, run_id, choose=lambda q: q["options"][0]["key"], max_pauses=50):
    """Answer every blocking question with `choose` and resume until the run stops pausing."""
    for _ in range(max_pauses):
        status = store.run(run_id)["status"]
        open_blocking = [q for q in store.questions(run_id, "open") if q["blocking"]]
        if status != "paused" and not (status == "completed_with_exceptions" and open_blocking):
            return status
        for q in store.questions(run_id, "open"):
            if q["blocking"]:
                opt = choose(q)
                needs = next(o for o in q["options"] if o["key"] == opt).get("needs_value")
                answer(store, q["id"], opt, value="2000-01-01" if needs else None, answered_by="user:test")
        runner.resume(run_id, "test", "user:test")
    raise AssertionError("run kept pausing")
