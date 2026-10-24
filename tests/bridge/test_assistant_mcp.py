import asyncio
import json

import pytest

from bridge.assistant import BridgeAssistant
from bridge.mcp_server import build_server


@pytest.fixture
def assistant(tmp_path, export_dir):
    a = BridgeAssistant(str(tmp_path / "run.db"))
    a.start_run(str(export_dir), target="embedded::memory:")
    return a


def test_guided_loop_to_completion(assistant):
    a = assistant
    assert a.run_status()["status"] == "paused"
    for _ in range(30):
        qs = a.list_questions(blocking_only=True)["questions"]
        if not qs and a.run_status()["status"] != "paused":
            break
        for q in qs:
            detail = a.get_question(q["id"])
            assert detail["prompt"] and detail["options"]
            opt = q["options"][0]
            res = a.answer_question(q["id"], opt["key"], "user:alice", value="12345" if opt.get("needs_value") else None)
            assert "error" not in res, res
        a.resume_run("answered with user", "user:alice")
    status = a.run_status()
    assert status["status"] in ("completed", "completed_with_exceptions")
    assert status["open_questions"]["blocking"] == 0
    assert a.loss_report()
    assert a.list_rules()


def test_guards(assistant):
    a = assistant
    q = a.list_questions()["questions"][0]
    assert "error" in a.answer_question(q["id"], q["options"][0]["key"], "assistant")  # blocking -> must be user
    assert "error" in a.answer_question(q["id"], q["options"][0]["key"], "bob")        # bad answered_by
    assert "error" in a.revert("run", confirm=False, confirmed_by="user:alice")
    assert "error" in a.revert("run", confirm=True, confirmed_by="assistant")


def test_assistant_may_answer_nonblocking_nonclinical(assistant):
    a = assistant
    for q in a.list_questions(blocking_only=True)["questions"]:
        a.answer_question(q["id"], q["options"][0]["key"], "user:alice")
    a.resume_run("go", "user:alice")
    nb = [q for q in a.list_questions()["questions"] if not q["blocking"] and not q["clinical"]]
    assert nb
    res = a.answer_question(nb[0]["id"], nb[0]["options"][0]["key"], "assistant", value="x", rationale="matches default")
    assert "error" not in res


def test_mcp_tools_registered_and_callable(assistant):
    server = build_server(assistant.run_db)

    async def go():
        names = {t.name for t in await server.list_tools()}
        assert {"run_status", "list_questions", "answer_question", "explain_record", "revert", "resume_run"} <= names
        res = await server.call_tool("run_status", {})
        text = res.content[0].text
        assert json.loads(text)["status"] == "paused"
        res = await server.call_tool("revert", {"scope": "run", "confirm": False, "confirmed_by": "user:x"})
        assert "error" in json.loads(res.content[0].text)
        docs = list(await server.read_resource("bridge://docs/ARCHITECTURE"))
        assert "Architecture" in docs[0].content

    asyncio.run(go())


def test_mcp_stdio_roundtrip(assistant):
    """Spawn the real server over stdio and call a tool, as an AI client would."""
    import sys

    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "bridge", "--run-db", assistant.run_db, "mcp"])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                assert any(t.name == "list_questions" for t in tools.tools)
                res = await s.call_tool("list_questions", {"blocking_only": True})
                assert json.loads(res.content[0].text)["total"] >= 1

    asyncio.run(go())
