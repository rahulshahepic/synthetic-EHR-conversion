import hashlib
import json
import sqlite3

import pytest

from testbed.halcyon.generator import generate


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    out = tmp_path_factory.mktemp("h")
    summary = generate(out, seed=7, patients=120)
    return out, summary


def _digest(path):
    con = sqlite3.connect(path)
    h = hashlib.sha256()
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        for row in con.execute(f"SELECT * FROM {t} ORDER BY 1"):
            h.update(repr(row).encode())
    return h.hexdigest()


def test_layout(export):
    out, _ = export
    for p in ["halcyon.db", "manifest.json", "feeds/adt_0001.hl7", "feeds/oru_0001.hl7", "feeds/siu_0001.hl7",
              "extracts/immunizations.csv", "extracts/charge_master.csv", "answer_key/issues.jsonl",
              "answer_key/persons.json", "answer_key/truth.json"]:
        assert (out / p).exists(), p


def test_deterministic(tmp_path, export):
    out, _ = export
    generate(tmp_path, seed=7, patients=120)
    assert _digest(out / "halcyon.db") == _digest(tmp_path / "halcyon.db")
    assert (out / "feeds/adt_0001.hl7").read_bytes() == (tmp_path / "feeds/adt_0001.hl7").read_bytes()


def test_planted_issue_variety(export):
    _, summary = export
    for kind in ["duplicate_person", "icd9_one_to_many", "feed_only_lab", "unrepresentable_status",
                 "implausible_vital", "uncodable_allergen", "generic_user", "shared_department"]:
        assert summary["issues"].get(kind, 0) > 0, kind


def test_answer_key_refers_to_real_rows(export):
    out, _ = export
    con = sqlite3.connect(out / "halcyon.db")
    pk = {"PAT": "PAT_ID", "DX": "DX_ID", "VISIT": "VISIT_ID", "ALLERGY": "ALG_ID", "VITALS": "VITAL_ID",
          "SCHED": "APPT_ID", "MED_ORD": "ORD_ID", "NOTE": "NOTE_ID", "COVERAGE": "COV_ID", "USERS": "USER_ID"}
    for line in (out / "answer_key/issues.jsonl").read_text().splitlines():
        issue = json.loads(line)
        if issue["table"] in pk:
            n = con.execute(f"SELECT COUNT(*) FROM {issue['table']} WHERE {pk[issue['table']]}=?", (issue["key"],)).fetchone()[0]
            assert n == 1, issue


def test_persons_cover_all_pats(export):
    out, _ = export
    persons = json.loads((out / "answer_key/persons.json").read_text())
    con = sqlite3.connect(out / "halcyon.db")
    pats = {r[0] for r in con.execute("SELECT PAT_ID FROM PAT")}
    assert pats == {p for ids in persons.values() for p in ids}


def test_registry_is_latin1(export):
    out, _ = export
    raw = (out / "extracts/immunizations.csv").read_bytes()
    raw.decode("latin-1")
    assert raw.splitlines()[0].startswith(b"MRN|FAC|")
