import asyncio

import pytest
from mcp import types
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession

from bridge.assistant import BridgeAssistant
from bridge.mcp_server import build_server


@pytest.fixture
def run_db(tmp_path, export_dir):
    a = BridgeAssistant(str(tmp_path / "run.db"))
    a.start_run(str(export_dir), target="embedded::memory:")
    return a


def _call(server, tool, args, elicitation_callback=None):
    async def go():
        async with InMemoryTransport(server) as (r, w):
            async with ClientSession(r, w, elicitation_callback=elicitation_callback) as s:
                await s.initialize()
                return await s.call_tool(tool, args)
    return asyncio.run(go())


def test_ask_user_records_the_humans_choice(run_db):
    a = run_db
    q = a.list_questions(blocking_only=True)["questions"][0]
    seen = {}

    async def human(context, params):
        seen["message"] = params.message
        seen["schema"] = params.requested_schema
        return types.ElicitResult(action="accept", content={"choice": "duplicate", "your_name": "Dana Smith"})

    res = _call(build_server(a.run_db), "ask_user", {"question_id": q["id"]}, human)
    assert not res.is_error, res
    assert "shared by all facilities" in seen["message"]
    assert set(seen["schema"]["properties"]["choice"]["enum"]) == {o["key"] for o in q["options"]}
    answered = a.get_question(q["id"])
    assert answered["status"] == "answered"
    assert answered["answer"]["answered_by"] == "user:dana-smith"


def test_ask_user_decline_records_nothing(run_db):
    a = run_db
    q = a.list_questions(blocking_only=True)["questions"][0]

    async def human(context, params):
        return types.ElicitResult(action="decline")

    _call(build_server(a.run_db), "ask_user", {"question_id": q["id"]}, human)
    assert a.get_question(q["id"])["status"] == "open"


def test_ask_user_without_elicitation_returns_text(run_db):
    a = run_db
    q = a.list_questions(blocking_only=True)["questions"][0]
    res = _call(build_server(a.run_db), "ask_user", {"question_id": q["id"]})
    text = res.content[0].text
    assert "unsupported" in text and "Options:" in text
    assert a.get_question(q["id"])["status"] == "open"
