"""T-117: MCP analyst interface — stub backend, estate firewall, replay."""
from __future__ import annotations

from pathlib import Path

import pytest

from bridge.interview import ledger as ledger_mod
from bridge.interview.analysts import (AnalystService, EstateReader,
                                       StubAnalyst, build_profile_prompt,
                                       replay_questions)


def _estate(tmp_path: Path) -> Path:
    root = tmp_path / "estate"
    (root / "analysts").mkdir(parents=True)
    (root / "answer_key").mkdir()
    (root / "DATADICT.TXT").write_text("DATA DICTIONARY VERSION 4.1")
    (root / "analysts" / "lab.md").write_text("# Tom\nThe L number is the patient.")
    (root / "answer_key" / "estate_discrepancies.json").write_text("[]")
    (root / "generator.py").write_text("# code, not estate")
    return root


def _service(tmp_path: Path) -> AnalystService:
    analysts = {
        "registration": StubAnalyst(
            id="registration", name="Marla Denny",
            answers={"What pivot year does the system use for two-digit years?":
                     "The window starts at 1930. 30 and up is 19-something."},
            blind_spots=["lab", "radiology"],
            outside_response="Outside my area. That's lab — ask Tom."),
        "systems": StubAnalyst(
            id="systems", name="Greg Holt",
            answers={"What pivot year does the system use for two-digit years?":
                     "The pivot year of 50: 00-49 are 20xx, 50-99 are 19xx."}),
    }
    return AnalystService(analysts, EstateReader([_estate(tmp_path)]))


def test_stub_answers_recorded_question_byte_for_byte(tmp_path):
    svc = _service(tmp_path)
    got = svc.ask("registration", "what pivot year does the system use for two-digit years")
    assert got["answer"] == "The window starts at 1930. 30 and up is 19-something."


def test_stub_blind_spot_and_unknown(tmp_path):
    svc = _service(tmp_path)
    assert svc.ask("registration", "How does the lab file encode dates?")["answer"] == \
        "Outside my area. That's lab — ask Tom."
    assert svc.ask("registration", "What is the cafeteria menu?")["answer"] == "I don't know."
    assert svc.ask("nobody", "Anything?")["error"]


def test_estate_allowlist(tmp_path):
    svc = _service(tmp_path)
    assert "DATA DICTIONARY" in svc.read_estate("DATADICT.TXT")["text"]
    # analyst profiles are NOT estate documents — the builder never reads them
    assert "error" in svc.read_estate("analysts/lab.md")
    # grading material is refused by construction
    assert "error" in svc.read_estate("answer_key/estate_discrepancies.json")
    # traversal and code are refused
    assert "error" in svc.read_estate("../TASKS.md")
    assert "error" in svc.read_estate("generator.py")
    assert "error" in svc.read_estate("missing.txt")


def test_replay_recorded_ledger(tmp_path):
    svc = _service(tmp_path)
    events = [
        ledger_mod.LedgerEvent("E000001", "question",
                               {"analyst": "registration",
                                "text": "What pivot year does the system use for two-digit years?"}),
        ledger_mod.LedgerEvent("E000002", "answer",
                               {"question_id": "E000001",
                                "text": "The window starts at 1930. 30 and up is 19-something."}),
        ledger_mod.LedgerEvent("E000003", "question",
                               {"analyst": "systems",
                                "text": "What pivot year does the system use for two-digit years?"}),
        ledger_mod.LedgerEvent("E000004", "answer",
                               {"question_id": "E000003",
                                "text": "The pivot year of 50: 00-49 are 20xx, 50-99 are 19xx."}),
    ]
    assert replay_questions(events, svc) == []
    tampered = events[:3] + [ledger_mod.LedgerEvent(
        "E000004", "answer", {"question_id": "E000003", "text": "The pivot is 30."})]
    assert len(replay_questions(tampered, svc)) == 1


def test_profile_prompt_is_scoped(tmp_path):
    prompt = build_profile_prompt("# Tom\nLab only.", {"DATADICT.TXT": "VERSION 4.1"})
    assert "only from the profile" in prompt and "VERSION 4.1" in prompt


def test_mcp_server_builds(tmp_path):
    from bridge.interview.analyst_server import build_server
    server = build_server([_estate(tmp_path)], {"registration": {"name": "Marla"}})
    assert server is not None
