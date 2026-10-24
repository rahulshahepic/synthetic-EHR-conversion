# Synthetic EHR Conversion

Proof of concept: convert a messy, invented legacy EHR (**Halcyon**) into an invented modern EHR (**Nimbus**) with **Bridge**, a conversion app that measures fidelity, monitors every batch, pauses on anomalies, can revert, and lets an AI chatbot help resolve reconciliation questions with a human (via MCP).

All data is synthetic.

## Repo map
```
docs/                 design docs — start with ARCHITECTURE.md, then PLAN.md
TASKS.md              task board for all contributors (incl. AI agents)
CONTRIBUTING.md       branch/claim rules — READ before working
src/nimbus/           target EHR (service + import API)
src/bridge/           the conversion application
testbed/halcyon/      synthetic legacy source EHR generator (test fixture only)
tests/                pytest suites
```

## Docs
- [Architecture](docs/ARCHITECTURE.md)
- [Plan & milestones](docs/PLAN.md)
- [Source: Halcyon](docs/source-halcyon.md)
- [Target: Nimbus & import API](docs/target-nimbus.md)
- [Mapping & fidelity](docs/mapping-and-fidelity.md)
- [Metrics, monitoring, pause & revert](docs/metrics-and-monitoring.md)
- [Reconciliation & AI (MCP)](docs/reconciliation-and-ai.md)

## See the runs on GitHub (no local setup)
Every merge to `main` runs the **Conversion demo** workflow. Open the repo's **Actions** tab → *Conversion demo* → latest run:
the **Summary** page shows the narrated transcript (pauses, questions answered, per-resource results, fidelity loss,
verification, go-live readiness, rehearsal comparison, cutover delta, second source system), and the **Artifacts**
section has the full HTML run report. To run it yourself: *Run workflow* (choose patient count / seed).

## See it in one command
```
pip install -e ".[dev]"
python -m testbed.demo --out demo_out --patients 300     # ~2 min; writes demo_out/DEMO_TRANSCRIPT.md
```
Generates a messy legacy export, runs rehearsal 1 with a simulated analyst answering Bridge's questions (through the same
operations the MCP server exposes), verifies, runs rehearsal 2 reusing the answers, then a cutover delta.

## Quickstart (step by step)
```
pip install -e ".[dev]"
python -m testbed.halcyon generate --out exports/seed42 --seed 42 --patients 500
python -m bridge --run-db runs/r1.db run --source exports/seed42     # embedded Nimbus (runs/r1_nimbus.db) by default
python -m bridge --run-db runs/r1.db status                            # pauses show here, with the reason
python -m bridge --run-db runs/r1.db questions                         # grouped reconciliation questions
python -m bridge --run-db runs/r1.db answer <qid> <option> --by user:you
python -m bridge --run-db runs/r1.db resume --note "why" --by user:you
python -m bridge --run-db runs/r1.db revert --scope run --cascade      # or --scope batch|type --target-id X
python -m bridge --run-db runs/r2.db run --source exports/seed42 --rules-from runs/r1.db   # rehearsal 2
python -m bridge --run-db runs/r2.db compare --other-run-db runs/r1.db
python -m bridge --run-db runs/cut.db run --source exports/seed42b --prior-run runs/r1.db   # cutover delta
python -m bridge --run-db runs/cut.db delta
python -m bridge --run-db runs/r1.db mcp                               # MCP server (stdio) for AI assistants
# connect from Claude Code: claude mcp add bridge -- python -m bridge --run-db "$PWD/runs/r1.db" mcp
```

## Working here as an AI agent (ChatGPT, Muse, Claude, ...)
Read `CONTRIBUTING.md`. In short: take a `ready` task from `TASKS.md`, claim it by pushing a branch `task/<ID>-<slug>` from `main` (if one exists, it's taken), work only in that branch, open a PR to `main`.
