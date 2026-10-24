import hashlib
import json
import sqlite3

import pytest

from testbed.halcyon.generator import generate
from testbed.halcyon.mutate import PKS, mutate


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    base = tmp_path_factory.mktemp("mut")
    generate(base / "a", seed=5, patients=90)
    summary = mutate(base / "a", base / "b", seed=3)
    return base / "a", base / "b", summary


def _table(path, table):
    con = sqlite3.connect(path / "halcyon.db")
    con.row_factory = sqlite3.Row
    return {r[PKS[table]]: dict(r) for r in con.execute(f"SELECT * FROM {table}")}


def test_delta_json_is_complete_and_keys_stable(pair):
    a, b, _ = pair
    delta = json.loads((b / "answer_key/delta.json").read_text())["tables"]
    for table in PKS:
        ta, tb = _table(a, table), _table(b, table)
        added, deleted = set(tb) - set(ta), set(ta) - set(tb)
        changed = {k for k in set(ta) & set(tb) if ta[k] != tb[k]}
        d = delta.get(table, {"added": [], "changed": [], "deleted": []})
        assert added == set(d["added"]), table
        assert deleted == set(d["deleted"]), table
        assert changed == set(d["changed"]), table


def test_every_kind_of_change_present(pair):
    _, b, summary = pair
    t = summary["tables"]
    assert t["PAT"]["added"] >= 2 and t["PAT"]["changed"] >= 2
    assert t["VISIT"]["added"] >= 3 and t["VITALS"]["added"] >= 3
    assert t["DX"]["deleted"] >= 1 and t["MED_ORD"]["changed"] >= 1
    assert summary["feeds"]["adt"] >= 4 and summary["feeds"].get("oru", 0) >= 1
    manifest = json.loads((b / "manifest.json").read_text())
    assert manifest["asOf"] == summary["as_of_b"] and manifest["derivedFrom"]["mutation"] == "T-111"


def test_feeds_appended_and_new_people_in_answer_key(pair):
    a, b, _ = pair
    assert (b / "feeds/adt_0001.hl7").read_bytes().startswith((a / "feeds/adt_0001.hl7").read_bytes())
    assert b"ADT^A08" in (b / "feeds/adt_0001.hl7").read_bytes()[len((a / "feeds/adt_0001.hl7").read_bytes()):]
    persons = json.loads((b / "answer_key/persons.json").read_text())
    added = json.loads((b / "answer_key/delta.json").read_text())["tables"]["PAT"]["added"]
    assert {p for ids in persons.values() for p in ids} >= set(added)


def test_deterministic(tmp_path, pair):
    a, b, _ = pair
    mutate(a, tmp_path / "b2", seed=3)
    digest = lambda p: hashlib.sha256((p / "answer_key/delta.json").read_bytes() + (p / "feeds/adt_0001.hl7").read_bytes()).hexdigest()  # noqa: E731
    assert digest(b) != "" and json.loads((b / "answer_key/delta.json").read_text())["tables"] == \
        json.loads((tmp_path / "b2/answer_key/delta.json").read_text())["tables"]
    assert (b / "feeds/adt_0001.hl7").read_bytes() == (tmp_path / "b2/feeds/adt_0001.hl7").read_bytes()
