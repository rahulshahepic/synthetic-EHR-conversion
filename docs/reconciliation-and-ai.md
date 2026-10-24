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

## MCP tools (v1)
| Tool | Purpose |
|---|---|
| `run_status(run_id?)` | State, progress per type, open alerts, open question counts. |
| `list_alerts(run_id, status?)` / `acknowledge_alert(id, note)` | Monitor breaches. |
| `get_metrics(run_id, resource_type?, batch_id?)` | Metric snapshot and trends. |
| `list_questions(run_id, kind?, blocking?, limit)` | Grouped open questions, highest impact first. |
| `get_question(id)` | Full context. |
| `answer_question(id, option_key, scope, rationale, answered_by)` | Records answer → creates mapping rule → marks affected records for reprocessing. |
| `explain_record(source_key)` | Lineage: raw source rows/segments → mapped payload → fidelity annotations → Nimbus result. |
| `loss_report(run_id, resource_type?)` | Dropped/degraded fields summary. |
| `pause_run` / `resume_run` / `reprocess(batch_id or held=true)` | Run control. |
| `revert(run_id, scope, target)` | Revert batch/type/run. **Destructive**: requires `confirm=true`; tool description tells the assistant to get explicit user consent first. |
| `list_rules` / `retire_rule(id)` | Mapping-rule management. |

MCP resources: `bridge://runs/{id}/summary`, `bridge://docs/{name}` (these docs, so the assistant can learn the domain).

## Safety rules for the assistant (embedded in tool descriptions)
- The assistant may *propose* answers but must not answer clinically significant questions (`blocking=true`, kinds: allergy, medication, identity merge) without the user explicitly choosing.
- Every answer stores `answered_by` (`user:<name>` vs `assistant`) and rationale; assistant-authored answers are allowed only for non-blocking kinds and are flagged for review.
- No PHI leaves the machine — everything here is synthetic anyway, but the design assumes it would be real.
