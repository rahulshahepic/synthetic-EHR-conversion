# Reconciliation Questions and the AI (MCP) Interface

Conversion produces questions only a human (clinician, HIM analyst, billing lead) can answer. Bridge queues them, and exposes the queue plus run control over **MCP** so an AI chatbot running locally (Claude Code, Claude Desktop, ChatGPT with MCP, etc.) can triage, explain, batch similar questions, and ask the user in plain language.

Run: `python -m bridge mcp --run-db bridge_run.db` (stdio transport).

## Question model
```
Question {
  id, run_id, kind,               # e.g. identity_match, icd9_one_to_many, unmapped_local_code, unparseable_sig,
                                  #      unit_ambiguous, allergy_conflict, unrepresentable_status, generic_user
  status: open | answered | superseded,
  blocking: bool,                 # true => records held until answered
  prompt,                         # plain-language question for a human
  context { source excerpts, candidate target values, counts of affected records },
  options [ {key, label, effect} ],   # always includes a "skip/degrade" option where safe
  scope_suggestion: record | code | pattern,
  affected_source_keys[],
  group_key                       # identical questions are grouped (answer once, apply to 200 records)
  answer { option_key, free_text, scope, answered_by, answered_at, rationale }
}
```

## MCP tools (v1, implemented in `src/bridge/mcp_server.py` over `src/bridge/assistant.py`)
| Tool | Purpose |
|---|---|
| `guide()` | The workflow below plus the list of docs. |
| `list_runs()` / `start_run(source, target?, batch_size?)` | Runs in this run DB; start converting an export (runs until first pause). |
| `run_status(run_id?)` | State, pause reason, per-type counts and fidelity, open alerts, open question counts. |
| `list_alerts(run_id?, status?)` / `acknowledge_alert(id, note, by, new_threshold?)` | Monitor breaches; acknowledging can raise a rule's threshold for that type. |
| `get_metrics(run_id?, resource_type?, batch_id?)` | Per-batch metric trend, or full detail for one batch. |
| `list_questions(run_id?, kind?, blocking_only?, status?, limit?)` | Grouped questions, blocking and highest impact first; flags `clinical`. |
| `get_question(id)` | Prompt, options, context and example source records. |
| `answer_question(id, option, answered_by, value?, rationale?)` | Answer → mapping rule → held records released / defaulted records requeued. |
| `explain_record(source_key, resource_type?)` | Lineage: source → mapped payload → fidelity annotations → Nimbus result. |
| `loss_report(run_id?, resource_type?)` | Dropped/degraded/inferred/defaulted fields summary. |
| `list_rules()` / `retire_rule(id, by)` | Mapping-rule management. |
| `recent_events()` | Batches, pauses, answers, reverts. |
| `pause_run` / `resume_run(note, by)` / `reprocess(statuses?, resource_type?)` | Run control. Resume acknowledges open alerts with the note. |
| `revert(scope, confirm, confirmed_by, target?, cascade?)` | **Destructive**; refused unless `confirm=true` and `confirmed_by="user:<name>"`. |

## Connecting an assistant (local checkout)
Claude Code:
```
claude mcp add bridge -- python -m bridge --run-db "$PWD/runs/demo.db" mcp
```
Any MCP client (Claude Desktop, ChatGPT desktop with MCP, etc.) — stdio server config:
```json
{"mcpServers": {"bridge": {"command": "python", "args": ["-m", "bridge", "--run-db", "/abs/path/runs/demo.db", "mcp"]}}}
```
Then e.g. *"Start a conversion of exports/seed42 and walk me through anything that needs my decision."*

MCP resources: `bridge://runs/{id}/summary`, `bridge://docs/{name}` (these docs, so the assistant can learn the domain).

## Safety rules for the assistant (embedded in tool descriptions)
- The assistant may *propose* answers but must not answer blocking or clinical questions (identity, problem codes, medications, labs, DOB, allergies) without the user explicitly choosing. This is enforced server-side: `answered_by="assistant"` is rejected for those.
- Every answer stores `answered_by` (`user:<name>` vs `assistant`) and rationale; assistant-authored answers are allowed only for non-blocking kinds and are flagged for review.
- No PHI leaves the machine — everything here is synthetic anyway, but the design assumes it would be real.
