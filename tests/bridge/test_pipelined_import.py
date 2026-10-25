"""Chunked, overlapped import must give exactly the outcome of one import call per batch."""
import json
import math
import random

import pytest

from bridge import jsonx
from bridge.load.client import connect
from bridge.runs import runner as runner_mod
from bridge.runs.runner import Runner
from bridge.runs.store import RunStore


def _outcome(store, client, rid):
    records = {(r[0], r[1]): (r[2], r[3], r[4]) for r in store.db.execute(
        "SELECT rtype, source_key, status, mapped, issues FROM records WHERE run_id=?", (rid,))}
    svc = client.http.app.state.service
    nimbus = {(r[0], r[1]): (r[2], json.loads(r[3])) for r in svc._db.execute(
        "SELECT rtype, source_key, version, data FROM resources")}
    def drop_ids(v):  # resource ids are random: compare references by sourceKey only
        if isinstance(v, dict):
            v.pop("id", None)
            for x in v.values():
                drop_ids(x)
        elif isinstance(v, list):
            for x in v:
                drop_ids(x)
    for _, data in nimbus.values():
        drop_ids(data)
    batches = [r[0] for r in store.db.execute("SELECT counts FROM batches WHERE run_id=? ORDER BY seq", (rid,))]
    return records, nimbus, batches


def _run(tmp_path, export_dir, drive, name, pipelined, monkeypatch, chunk=7, types=None):
    store = RunStore(str(tmp_path / f"{name}.db"))
    client = connect("embedded::memory:")
    client.out_of_process = pipelined  # force chunking against the in-process Nimbus
    monkeypatch.setattr(runner_mod, "PIPELINE_CHUNK", chunk)
    runner = Runner(store, client)
    rid = runner.start(str(export_dir), types=types)
    drive(store, runner, rid)
    return _outcome(store, client, rid)


def test_chunked_import_matches_single_call(tmp_path, export_dir, drive, monkeypatch):
    single = _run(tmp_path, export_dir, drive, "single", False, monkeypatch)
    chunked = _run(tmp_path, export_dir, drive, "chunked", True, monkeypatch)
    assert single[0] == chunked[0]  # record statuses, mapped payloads, issues
    assert single[1] == chunked[1]  # Nimbus contents
    assert [json.loads(b) for b in single[2]] == [json.loads(b) for b in chunked[2]]  # per-batch counts


def test_failure_mid_batch_rolls_back_imported_chunks(tmp_path, export_dir, monkeypatch):
    store = RunStore(str(tmp_path / "fail.db"))
    client = connect("embedded::memory:")
    client.out_of_process = True
    monkeypatch.setattr(runner_mod, "PIPELINE_CHUNK", 5)
    runner = Runner(store, client)
    rid = runner.start(str(export_dir), auto_execute=False, types=["Practitioner"])
    original = runner_mod.MapContext.__init__
    seen = {"n": 0}

    def flaky(self, *a, **k):
        original(self, *a, **k)
        if self.rtype == "Practitioner":
            seen["n"] += 1
            if seen["n"] == 23:  # after four chunks of five have been sent
                raise OSError("disk full")
    monkeypatch.setattr(runner_mod.MapContext, "__init__", flaky)
    with pytest.raises(OSError):
        runner.execute(rid)
    svc = client.http.app.state.service
    assert svc.count("Practitioner")["total"] == 0  # the imported chunks were rolled back
    assert store.status_counts(rid)["Practitioner"] == {"pending": sum(store.status_counts(rid)["Practitioner"].values())}


def test_jsonx_dumps_parses_like_stdlib():
    import datetime
    cases = [{"a": [1.5, -0.0, 1e16, 1e-7, None, True, "é  ", {"x": "😀"}]}, {"nan": float("nan")},
             [float("inf")], {"d": datetime.datetime(2021, 3, 15, 12, 30)}, (1, 2), {1: "int key"}, {"big": 2 ** 80},
             "lone \ud800 surrogate", 0.12345678901234567, [], {}, ""]
    rng = random.Random(3)

    def rnd(depth=0):
        if depth > 3 or rng.random() < 0.3:
            return rng.choice([rng.random() * 10 ** rng.randint(-8, 20), rng.randint(-10 ** 25, 10 ** 25), "s", None, True, "ü"])
        if rng.random() < 0.5:
            return [rnd(depth + 1) for _ in range(rng.randint(0, 3))]
        return {f"k{i}": rnd(depth + 1) for i in range(rng.randint(0, 3))}
    for value in cases + [rnd() for _ in range(5000)]:
        assert repr(json.loads(jsonx.dumps(value))) == repr(json.loads(json.dumps(value, default=str)))
    assert jsonx.dumps({"nan": float("nan")}) == json.dumps({"nan": float("nan")})  # NaN stays NaN, never null
    assert math.isnan(json.loads(jsonx.dumps([float("nan")]))[0])


CONDITION_PATH = ["Organization", "Location", "Practitioner", "Patient", "Encounter", "Condition"]


def test_mapping_never_sees_its_own_batch_outcomes(tmp_path, export_dir, drive, monkeypatch):
    """A duplicate whose first copy Nimbus rejects: mapped before any outcome is persisted, the later copy still
    sees the first one as pending and is superseded, exactly as with a single import call per batch."""
    _run(tmp_path, export_dir, drive, "probe", False, monkeypatch, types=CONDITION_PATH)
    store = RunStore(str(tmp_path / "probe.db"))
    owners = {r[0].split("duplicate of ")[1] for r in store.db.execute(
        "SELECT note FROM records WHERE rtype='Condition' AND status='superseded' AND note LIKE 'duplicate of %'")}
    assert owners

    from nimbus import service as nimbus_service
    real = nimbus_service.NimbusService._submit_one

    def reject_owners(self, batch, rec, ref_cache=None):
        if batch["resourceType"] == "Condition" and rec.get("sourceKey") in owners:
            return {"sourceKey": rec["sourceKey"], "status": "rejected",
                    "issues": [{"code": "E_TEST", "message": "rejected by test", "field": None, "severity": "error"}]}
        return real(self, batch, rec, ref_cache)
    monkeypatch.setattr(nimbus_service.NimbusService, "_submit_one", reject_owners)
    single = _run(tmp_path, export_dir, drive, "single_rej", False, monkeypatch, chunk=1, types=CONDITION_PATH)
    chunked = _run(tmp_path, export_dir, drive, "chunked_rej", True, monkeypatch, chunk=1, types=CONDITION_PATH)
    assert single[0] == chunked[0]
    assert single[1] == chunked[1]
