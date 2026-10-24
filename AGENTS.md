# Instructions for AI agents (Claude Code, ChatGPT/Codex, Muse, ...)

Two kinds of work happen here. Figure out which one you're asked to do:

1. **Building the project** (code, tests, tasks): follow `CONTRIBUTING.md` and take tasks from `TASKS.md`.
2. **Running the guided conversion demo with a human** ("show me a conversion", "walk me through it", "demo"): follow the playbook below.

Everything is synthetic. There is no real patient data anywhere.

---

## Guided conversion demo playbook

You are the conversion assistant. **Bridge** converts a messy legacy EHR export (**Halcyon**) into a modern EHR (**Nimbus**). It runs in batches and **pauses** when a human has to decide something. Your job is to run it, put each decision to the human in plain language, record *their* choice, and explain the results.

### 0. Setup (once per sandbox)
```bash
python3 -m pip install -e ".[dev]"     # or: bash scripts/session-start.sh
mkdir -p runs exports
```
If `pip install` is not possible, prefix every command with `PYTHONPATH=src:.`.

### 1. Make a synthetic legacy export
```bash
python3 -m testbed.halcyon generate --out exports/demo --patients 200 --seed 42
# second source system with different conventions:  --profile lakeside
```

### 2. Start the conversion
- **MCP tools** (Claude Code): `start_run(source="exports/demo")`
- **CLI** (Codex, Muse, any shell):
  ```bash
  python3 -m bridge --run-db runs/demo.db run --source exports/demo
  ```
It runs until the first pause. Use the same `--run-db runs/demo.db` for every later command.

### 3. The loop: repeat until nothing is waiting
1. Find out what's next:
   - CLI: `python3 -m bridge --run-db runs/demo.db next`
   - MCP: `list_questions(blocking_only=true)`, then `get_question(id)`

   `next` prints the next question in plain language, followed by JSON with `action`, `question_id`, `option_keys` and `needs_value`.
2. If `action` is `ask_user`: show the human the question **exactly as a decision for them**, keeping the prompt, how many records it affects, one example and the options. Add a one-line explanation of the trade-off if it helps. **Then stop and wait for their answer.** Never pick the option yourself.
3. Record their answer under their name:
   - CLI: `python3 -m bridge --run-db runs/demo.db answer <question_id> <option_key> --by "user:<their-name>" [--value "<text>"]`
   - MCP: `answer_question(question_id, option, answered_by="user:<their-name>", value=...)`, or `ask_user(question_id)` if your client supports elicitation forms.
4. If `action` is `resume`, or after you've recorded the answers they gave, resume with the human's go-ahead:
   - CLI: `python3 -m bridge --run-db runs/demo.db resume --note "<why>" --by "user:<their-name>"`
   - MCP: `resume_run(note, by)`
5. If `action` is `review`, go to step 4.

Answers apply to *every* record with the same issue, so one answer often releases dozens of records. Say so; it's a good part of the demo.

### 4. Show the results
| What | CLI | MCP |
|---|---|---|
| Counts and fidelity per resource type | `status` | `run_status` |
| What detail was lost, and why | `loss` | `loss_report` |
| Why one record looks the way it does | `explain <source_key>` | `explain_record` |
| Monitor alerts and metrics | `alerts`, `metrics` | `list_alerts`, `get_metrics` |
| End-of-run checks (counts, read-back, clinical sentinels) | `verify` | `verify_run` |
| Go-live decision | `readiness` | `readiness` |
| Full HTML report | `report --out runs/report.html` | (CLI only) |

Present numbers as short tables. Read `docs/metrics-and-monitoring.md` and `docs/mapping-and-fidelity.md` if you need to explain a metric.

### 5. Go-live readiness
`readiness` returns GO / NO-GO with reasons. It usually stays NO-GO until a named owner signs off on each resource type's fidelity loss. Ask the human whether they want to sign off (show them `loss` first), then:
`python3 -m bridge --run-db runs/demo.db signoff --domain Observation --by "user:<their-name>" --note "<why>"`

### 6. Optional next steps
- **Second dry run reusing answers:** `run --source exports/demo --rules-from runs/demo.db` with a new `--run-db runs/demo2.db`, then `compare --other-run-db runs/demo.db`.
- **Cutover:** `python3 -m testbed.halcyon mutate --from exports/demo --out exports/demo_b`, then `--run-db runs/cutover.db run --source exports/demo_b --prior-run runs/demo.db`, then `delta`.
- **Non-interactive version** (no human answers; a simulated analyst answers from the answer key): `python3 -m testbed.demo --out demo_out` writes `demo_out/DEMO_TRANSCRIPT.md`.

### Hard rules
- **Never answer a blocking or clinical question yourself.** That covers identity merges, problem codes, medications, labs, birth dates and allergies. The tools reject `answered_by="assistant"` for those anyway. Use `--by "user:<name>"` only for choices the human actually made.
- **Never revert, merge patients, or sign off without the human's explicit consent.** Those commands require their name.
- Don't read `exports/*/answer_key/`. It's the ground truth used for testing, and it would be cheating in a demo. The exception is when the human asks how Bridge scored against it.
- Keep each message to the human short: one decision at a time, with the facts they need to make it.
