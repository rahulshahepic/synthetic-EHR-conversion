"""The chat-demo wiring for AI agents: .mcp.json, Claude settings/hook, AGENTS.md commands, `bridge next`."""
import asyncio
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _expand(value: str) -> str:
    return re.sub(r"\$\{CLAUDE_PROJECT_DIR:-[^}]*\}", str(ROOT), value)


def test_claude_settings_and_hook():
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    assert settings["enableAllProjectMcpServers"] is True
    cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "scripts/session-start.sh" in cmd
    hook = ROOT / "scripts/session-start.sh"
    assert hook.stat().st_mode & stat.S_IXUSR
    r = subprocess.run(["bash", str(hook)], env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}, capture_output=True, timeout=600)
    assert r.returncode == 0, r.stderr


def test_mcp_json_launches_the_bridge_server(tmp_path):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["bridge"]
    args = [_expand(a) for a in server["args"]]
    args[args.index("--run-db") + 1] = str(tmp_path / "chat.db")  # don't touch the real runs/ dir
    env = {k: _expand(v) for k, v in server["env"].items()}
    command = sys.executable if server["command"] in ("python", "python3") else server["command"]

    async def go():
        params = StdioServerParameters(command=command, args=args, env=env, cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert {"start_run", "list_questions", "ask_user", "answer_question", "resume_run", "readiness"} <= names

    asyncio.run(go())


def test_agents_md_cli_commands_exist():
    from bridge.__main__ import main
    text = (ROOT / "AGENTS.md").read_text()
    used = set(re.findall(r"python3 -m bridge --run-db \S+ (\w[\w-]*)", text))
    used |= {m for m in re.findall(r"`(\w[\w-]*)(?: [^`]*)?`", text)
             if m in {"status", "loss", "explain", "alerts", "metrics", "verify", "readiness", "report", "next", "signoff",
                      "compare", "delta"}}
    assert {"run", "next", "answer", "resume", "signoff"} <= used
    import contextlib
    import io
    for cmd in sorted(used):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            try:
                main([cmd, "--help"])
            except SystemExit as e:
                assert e.code == 0, f"bridge subcommand {cmd!r} from AGENTS.md does not exist"


def test_next_tells_the_assistant_what_to_ask(tmp_path, monkeypatch, capsys):
    from bridge.__main__ import main
    from testbed.halcyon.generator import generate
    generate(tmp_path / "exp", seed=4, patients=40)
    db = str(tmp_path / "demo.db")
    main(["--run-db", db, "run", "--source", str(tmp_path / "exp"), "--target", "embedded::memory:"])
    capsys.readouterr()
    main(["--run-db", db, "next"])
    out = capsys.readouterr().out
    text, _, meta = out.partition("\n---\n")
    step = json.loads(meta)
    assert step["action"] == "ask_user" and step["question_id"] and "Options:" in text


def test_next_drives_the_cli_loop_to_review(tmp_path, capsys):
    """Answer every blocking question as a human would, via `next`/`answer`/`resume`, until `next` says review,
    and no record is left waiting (regression: answers given after the run finished left records pending)."""
    from bridge.__main__ import main
    from testbed.halcyon.generator import generate
    generate(tmp_path / "exp", seed=4, patients=40)
    db = str(tmp_path / "demo.db")
    main(["--run-db", db, "run", "--source", str(tmp_path / "exp"), "--target", f"embedded:{tmp_path / 'n.db'}"])
    for _ in range(60):
        capsys.readouterr()
        main(["--run-db", db, "next"])
        step = json.loads(capsys.readouterr().out.partition("\n---\n")[2])
        if step["action"] == "ask_user":
            opt = step["option_keys"][0]
            extra = ["--value", "2000-01-01"] if opt in step["needs_value"] else []
            main(["--run-db", db, "answer", step["question_id"], opt, "--by", "user:demo", *extra])
        elif step["action"] == "resume":
            main(["--run-db", db, "resume", "--note", "go", "--by", "user:demo"])
        else:
            break
    assert step["action"] == "review"
    from bridge.runs.store import RunStore
    store = RunStore(db)
    counts = store.status_counts(store.run()["id"])
    assert not any(c.get("pending") or c.get("held") for c in counts.values()), counts
