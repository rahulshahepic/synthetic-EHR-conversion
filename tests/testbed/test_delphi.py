"""Delphi generator: determinism, layout round-trips, answer-key schema, and
planted-issue coverage for the new pathologies."""
import hashlib
import json
from pathlib import Path

import pytest

from testbed.delphi import layouts
from testbed.delphi.generator import generate

DIGEST_7_25 = "deb1bbe7b4cd3c4d8a33a31c6b9393fae5e5abaa6ebf3d159fc9045d6b811703"  # re-pinned: grading ledger extended (PR #38 review)

NEW_ISSUE_TYPES = {
    "century_window_dob", "cross_department_duplicate", "truncated_name",
    "flag_string_result", "shorthand_dx", "invalid_julian_date", "julian_date_shift",
    "invalid_time_minutes", "name_variant", "dob_variant", "duplicate_registration",
    "free_text_dx", "unmappable_lab", "unmappable_charge", "unrepresentable_status",
}


@pytest.fixture(scope="module")
def export(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("delphi")
    generate(out, seed=42, patients=60)
    return out


def digest_tree(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_determinism_digest(tmp_path):
    generate(tmp_path, seed=7, patients=25)
    assert digest_tree(tmp_path) == DIGEST_7_25


def test_same_seed_identical_extracts(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, seed=3, patients=10)
    generate(b, seed=3, patients=10)
    for name in layouts.FILES.values():
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def parse_layouts_dat(text: str) -> dict:
    """Re-derive layouts from the shipped LAYOUTS.DAT, the way a consumer would."""
    derived: dict[str, dict[str, list]] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith(("FILE|", "#")):
            continue
        f, rt, name, start, length, _typ, _desc = line.split("|")
        derived.setdefault(f, {}).setdefault(rt, []).append((name, int(start), int(length)))
    return derived


def test_layouts_dat_matches_code_layouts(export):
    derived = parse_layouts_dat((export / "LAYOUTS.DAT").read_text())
    assert derived.keys() == {f for f, _ in layouts.LAYOUTS}
    for (stem, rt), spans in layouts.SPANS.items():
        code = [(name, start + 1, width) for name, start, width, _, _ in spans]
        assert derived[stem][rt] == code, f"{stem}/{rt}"


def test_every_record_parses_under_its_layout(export):
    rts_by_file: dict[str, set] = {}
    for f, rt in layouts.LAYOUTS:
        rts_by_file.setdefault(f, set()).add(rt)
    for stem, fname in layouts.FILES.items():
        path = export / fname
        assert path.exists(), fname
        for line in path.read_text(encoding="latin-1").splitlines():
            rt = line[:2].strip()
            assert rt in rts_by_file[stem], f"{fname}: unknown record type {rt!r}"
            assert len(line) == layouts.record_length(stem), f"{fname}: bad width"
            row = layouts.parse_record(stem, line)
            # re-rendering the parsed row reproduces the line exactly
            assert layouts.format_record(stem, rt, row) == line, f"{fname}/{rt}: no round-trip"


def test_fixed_width_files_have_no_delimiters_or_hl7(export):
    for fname in ("REG.TXT", "LAB.TXT", "PHA.TXT", "ENC.TXT"):
        text = (export / fname).read_text(encoding="latin-1")
        assert "|" not in text and "~" not in text


def test_answer_key_schema(export):
    persons = json.loads((export / "answer_key" / "persons.json").read_text())
    assert len(persons) == 60
    multi = [v for v in persons.values() if len(v) >= 2]
    assert len(multi) >= 40, "most persons should span several departmental accounts"
    truth = json.loads((export / "answer_key" / "truth.json").read_text())
    for key in ("person", "dx", "med", "lab", "appt_status", "a08_demographics",
                "provider_specialty", "visit_class"):
        assert key in truth, key
    issues = [json.loads(l) for l in (export / "answer_key" / "issues.jsonl").read_text().splitlines()]
    for issue in issues:
        assert {"type", "table", "key"} <= issue.keys()
    manifest = json.loads((export / "manifest.json").read_text())
    assert manifest["system"] == "Delphi"
    assert manifest["counts"]["REG"] >= 55


def test_new_issue_types_are_planted(tmp_path):
    generate(tmp_path, seed=42, patients=200)
    issues = [json.loads(l) for l in (tmp_path / "answer_key" / "issues.jsonl").read_text().splitlines()]
    planted = {i["type"] for i in issues}
    missing = NEW_ISSUE_TYPES - planted
    assert not missing, f"never planted: {sorted(missing)}"


def test_century_window_issues_carry_true_dob(export):
    issues = [json.loads(l) for l in (export / "answer_key" / "issues.jsonl").read_text().splitlines()]
    century = [i for i in issues if i["type"] == "century_window_dob"]
    assert century
    for issue in century:
        assert issue["true_dob"] < "1930-01-01", "pivot 30 only breaks pre-1930 births"


def test_journal_is_the_change_feed(export):
    lines = (export / "JOURNAL.TXT").read_text(encoding="latin-1").splitlines()
    ops = {layouts.parse_record("JOURNAL", ln)["OP"] for ln in lines}
    assert ops == {"A", "C", "D"}
    # the registration test account is journaled and deleted, never extracted
    reg = (export / "REG.TXT").read_text(encoding="latin-1")
    assert "R999999" not in reg
    assert any("R999999" in ln for ln in lines)
