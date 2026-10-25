"""MCP server for the Socratic interview: analysts + estate documents.

Run standalone (stdio) or embed via build_server(). Follows the patterns of
bridge/mcp_server.py. The tools are the whole interview surface:

- ``ask(analyst, question)`` — the ONLY way to reach an analyst. Analyst
  profiles are the backend's private knowledge and are never returned.
- ``read_estate(document)`` — estate documents under a path allowlist
  (see analysts.EstateReader). Grading material and analyst profiles are
  refused by construction, not by policy.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .analysts import AnalystService, EstateReader, StubAnalyst

INSTRUCTIONS = """You are interviewing a legacy source system's analysts to build its import spec.
Rules: reach analysts only through ask(); never ask for an analyst's profile (it is not available);
read estate documents through read_estate(); record every question, answer, claim and resolution
in the interview ledger as you go; a fact enters the spec only as a claim with provenance."""


def build_server(estate_roots: list[str | Path], stub_profiles: dict[str, dict[str, Any]]):
    from mcp.server.mcpserver import MCPServer

    analysts = {aid: StubAnalyst(id=aid, name=cfg.get("name", aid),
                                 answers=cfg.get("answers", {}),
                                 blind_spots=cfg.get("blind_spots", []),
                                 outside_response=cfg.get("outside_response", "Outside my area."),
                                 unknown_response=cfg.get("unknown_response", "I don't know."))
                for aid, cfg in stub_profiles.items()}
    service = AnalystService(analysts, EstateReader(estate_roots))
    mcp = MCPServer(name="bridge-analysts", title="Bridge Socratic interview",
                    instructions=INSTRUCTIONS, version="0.1")

    @mcp.tool(description="Ask one analyst a question. Answers come from the analyst alone; "
                          "you cannot inspect their profile or notes.")
    def ask(analyst: str, question: str) -> dict[str, Any]:
        return service.ask(analyst, question)

    @mcp.tool(description="Read an estate document (manual, dictionary, layout, manifest, "
                          "extract). Analyst profiles and grading material are not estate "
                          "documents and are refused.")
    def read_estate(document: str) -> dict[str, Any]:
        return service.read_estate(document)

    return mcp
