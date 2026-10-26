"""MCP server exposing Bridge to AI assistants (stdio). Run: python -m bridge --run-db runs/r1.db mcp"""
from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field, create_model

from .assistant import DOCS, WORKFLOW, BridgeAssistant, present

INSTRUCTIONS = WORKFLOW + """
Rules: never answer a blocking or clinical question (identity, problem codes, medications, labs, DOB, allergies)
without the user explicitly choosing; always pass answered_by="user:<name>" when relaying their choice.
Group your questions to the user: one answer usually releases many records."""


def build_server(run_db: str) -> MCPServer:
    b = BridgeAssistant(run_db)
    mcp = MCPServer(name="bridge", title="Bridge EHR conversion", instructions=INSTRUCTIONS, version="0.1")

    @mcp.tool(description="How to work with Bridge: the reconciliation workflow and available docs.")
    def guide() -> dict[str, Any]:
        return b.guide()

    @mcp.tool(description="What to do next in the guided demo: the next human question rendered in plain language "
                          "(action=ask_user), or resume / review / wait. Call it after every answer or resume.")
    def next_step(run_id: str | None = None) -> dict[str, Any]:
        return b.next_step(run_id)

    @mcp.tool(description="List conversion runs in this run database.")
    def list_runs() -> list[dict[str, Any]]:
        return b.list_runs()

    @mcp.tool(description="Run state, per-resource-type counts and fidelity, open alerts, open question counts. "
                          "run_id defaults to the latest run.")
    def run_status(run_id: str | None = None) -> dict[str, Any]:
        return b.run_status(run_id)

    @mcp.tool(description="Monitor alerts (status: open | acknowledged | None for all) with samples and suggested actions.")
    def list_alerts(run_id: str | None = None, status: str | None = "open") -> list[dict[str, Any]]:
        return b.list_alerts(run_id, status)

    @mcp.tool(description="Per-batch metrics (reject/hold rates, fidelity, code coverage). Pass batch_id for full detail.")
    def get_metrics(run_id: str | None = None, resource_type: str | None = None, batch_id: str | None = None) -> list[dict[str, Any]]:
        return b.get_metrics(run_id, resource_type, batch_id)

    @mcp.tool(description="Grouped reconciliation questions, blocking and highest-impact first. Each answer becomes a "
                          "mapping rule applied to every affected record.")
    def list_questions(run_id: str | None = None, kind: str | None = None, blocking_only: bool = False,
                       status: str = "open", limit: int = 25) -> dict[str, Any]:
        return b.list_questions(run_id, kind, blocking_only, status, limit)

    @mcp.tool(description="Full context for one question, with example source records, to explain it to the user.")
    def get_question(question_id: str) -> dict[str, Any]:
        return b.get_question(question_id)

    @mcp.tool(description="Record the USER's answer to a question. answered_by must be 'user:<name>' when relaying "
                          "the user's choice, or 'assistant' (allowed only for non-blocking, non-clinical questions). "
                          "Options with needs_value require `value`. Released records load on the next resume_run.")
    def answer_question(question_id: str, option: str, answered_by: str, value: str | None = None,
                        rationale: str = "") -> dict[str, Any]:
        return b.answer_question(question_id, option, answered_by, value, rationale)

    @mcp.tool(description="Ask the human directly: shows the question's options to the user as a form via MCP elicitation "
                          "and records their choice as their answer (never as the assistant's). If the client cannot elicit, "
                          "returns plain-language text for you to relay, then call answer_question with the user's choice.")
    async def ask_user(question_id: str, ctx: Context) -> dict[str, Any]:
        q = b.get_question(question_id)
        if q["status"] != "open":
            return {"error": f"question {question_id} is {q['status']}"}
        text = present(q)
        caps = ctx.client_capabilities
        if caps is None or getattr(caps, "elicitation", None) is None:
            return {"elicitation": "unsupported", "present_to_user": text}
        keys = tuple(o["key"] for o in q["options"])
        fields: dict[str, Any] = {
            "choice": (Literal[keys], Field(description="; ".join(f"{o['key']} = {o['label']}" for o in q["options"]))),
            "your_name": (str, Field(description="your name, recorded as the person who decided")),
        }
        if any(o.get("needs_value") for o in q["options"]):
            fields["value"] = (str, Field(default="", description="required if your choice asks you to enter a value"))
        schema = create_model("BridgeAnswer", **fields)
        result = await ctx.elicit(text, schema)
        if result.action != "accept" or result.data is None:
            return {"action": result.action, "note": "no answer recorded"}
        data = result.data
        name = "".join(ch for ch in data.your_name.strip().lower().replace(" ", "-") if ch.isalnum() or ch in "-_.") or "unknown"
        return b.answer_question(question_id, data.choice, f"user:{name}", value=getattr(data, "value", "") or None,
                                 rationale="answered by the user via elicitation")

    @mcp.tool(description="Lineage for a record: source rows/segments, mapped Nimbus payload, per-field fidelity "
                          "annotations, Nimbus issues and id. Partial keys are searched.")
    def explain_record(source_key: str, resource_type: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        return b.explain_record(source_key, resource_type, run_id)

    @mcp.tool(description="What fidelity was lost: counts of inferred/degraded/defaulted/dropped fields by type and field.")
    def loss_report(run_id: str | None = None, resource_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return b.loss_report(run_id, resource_type, limit)

    @mcp.tool(description="Active mapping rules created from answers.")
    def list_rules(run_id: str | None = None) -> list[dict[str, Any]]:
        return b.list_rules(run_id)

    @mcp.tool(description="Recent run events (batches, pauses, answers, reverts).")
    def recent_events(run_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return b.recent_events(run_id, limit)

    @mcp.tool(description="Acknowledge an alert with a note; optionally set a new threshold for that rule and type.")
    def acknowledge_alert(alert_id: str, note: str, by: str, new_threshold: float | None = None) -> dict[str, Any]:
        return b.acknowledge_alert(alert_id, note, by, new_threshold)

    @mcp.tool(description="Start a conversion of a Halcyon export directory. Runs until the first pause or completion. "
                          "rules_from: a prior rehearsal's run DB (or exported rules JSON) whose answers are reused. "
                          "prior_run_db: cutover/delta run against the prior run's target; also detects source deletions. "
                          "profile: 'halcyon' (default) or a source profile generated by the Socratic import builder, "
                          "e.g. 'meridian' for a Meridian MCS/2 export.")
    def start_run(source: str, target: str | None = None, batch_size: int = 200, rules_from: str | None = None,
                  prior_run_db: str | None = None, profile: str = "halcyon") -> dict[str, Any]:
        return b.start_run(source, target, batch_size, rules_from, prior_run_db, profile)

    @mcp.tool(description="Delta summary of a run: created / updated / unchanged / source_deleted per resource type.")
    def delta_summary(run_id: str | None = None) -> dict[str, Any]:
        return b.delta_summary(run_id)

    @mcp.tool(description="Merge two already-loaded Nimbus patients found to be the same person (Bridge patient keys, "
                          "e.g. H-P000123). Moves all clinical data to the survivor; revertible via revert(scope='batch'). "
                          "Requires the user's explicit confirmation: confirmed_by='user:<name>'.")
    def merge_patients(survivor: str, duplicate: str, confirmed_by: str, run_id: str | None = None) -> dict[str, Any]:
        return b.merge_patients(survivor, duplicate, confirmed_by, run_id)

    @mcp.tool(description="Go-live readiness: GO / NO-GO with reasons (blocking questions, unresolved records, unacknowledged "
                          "pause alerts, verification, fidelity-loss sign-offs) and warnings.")
    def readiness(run_id: str | None = None) -> dict[str, Any]:
        return b.readiness(run_id)

    @mcp.tool(description="A named owner accepts the current fidelity loss for one resource type (see loss_report). Only "
                          "relay this for the user who owns that domain: by='user:<name>'. Re-sign if the loss changes.")
    def signoff_domain(domain: str, by: str, note: str = "", run_id: str | None = None) -> dict[str, Any]:
        return b.signoff_domain(domain, by, note, run_id)

    @mcp.tool(description="Compare this run with an earlier rehearsal (other_run_db): questions, pauses, counts, fidelity.")
    def compare_runs(other_run_db: str, run_id: str | None = None) -> dict[str, Any]:
        return b.compare_runs(other_run_db, run_id)

    @mcp.tool(description="Resume a paused run (acknowledges open alerts with `note`). Get the user's go-ahead first.")
    def resume_run(note: str, by: str, run_id: str | None = None) -> dict[str, Any]:
        return b.resume_run(note, by, run_id)

    @mcp.tool(description="Pause a run.")
    def pause_run(reason: str, by: str, run_id: str | None = None) -> dict[str, Any]:
        return b.pause_run(reason, by, run_id)

    @mcp.tool(description="Requeue records with the given statuses (default: rejected) for another attempt on resume.")
    def reprocess(run_id: str | None = None, statuses: list[str] | None = None, resource_type: str | None = None) -> dict[str, Any]:
        return b.reprocess(run_id, statuses, resource_type)

    @mcp.tool(description="DESTRUCTIVE: remove converted data from Nimbus by batch, resource type, or whole run. Only "
                          "after the user explicitly confirms; pass confirm=true and confirmed_by='user:<name>'.")
    def revert(scope: str, confirm: bool, confirmed_by: str, target: str | None = None, cascade: bool = False,
               run_id: str | None = None) -> dict[str, Any]:
        return b.revert(scope, confirm, confirmed_by, target, cascade, run_id)

    @mcp.tool(description="End-of-run verification: Nimbus vs Bridge counts, read-back sample comparison, and clinical "
                          "sentinels (active anticoagulants/insulin, patients with allergies, abnormal labs).")
    def verify_run(run_id: str | None = None) -> dict[str, Any]:
        return b.verify_run(run_id)

    @mcp.tool(description="Retire a mapping rule (future mapping will ask again).")
    def retire_rule(rule_id: str, by: str) -> dict[str, Any]:
        return b.retire_rule(rule_id, by)

    @mcp.resource("bridge://docs/{name}", description="Bridge design docs (architecture, mapping, metrics, ...).",
                  mime_type="text/markdown")
    def doc(name: str) -> str:
        path = DOCS / f"{name}.md"
        return path.read_text() if path.exists() else f"no doc named {name}"

    return mcp


def serve(run_db: str) -> None:
    build_server(run_db).run("stdio")
