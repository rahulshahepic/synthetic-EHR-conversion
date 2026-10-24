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

## Quickstart (as milestones land)
```
pip install -e ".[dev]"
python -m testbed.halcyon generate --out exports/seed42 --seed 42 --patients 500
python -m bridge --run-db runs/r1.db run --source exports/seed42     # embedded Nimbus (runs/r1_nimbus.db) by default
python -m bridge --run-db runs/r1.db status                            # pauses show here, with the reason
python -m bridge --run-db runs/r1.db questions                         # grouped reconciliation questions
python -m bridge --run-db runs/r1.db answer <qid> <option> --by user:you
python -m bridge --run-db runs/r1.db resume --note "why" --by user:you
python -m bridge --run-db runs/r1.db revert --scope run --cascade      # or --scope batch|type --target-id X
python -m bridge --run-db runs/r1.db mcp                               # MCP server (stdio) for AI assistants
# connect from Claude Code: claude mcp add bridge -- python -m bridge --run-db "$PWD/runs/r1.db" mcp
```

## Working here as an AI agent (ChatGPT, Muse, Claude, ...)
Read `CONTRIBUTING.md`. In short: take a `ready` task from `TASKS.md`, claim it by pushing a branch `task/<ID>-<slug>` from `main` (if one exists, it's taken), work only in that branch, open a PR to `main`.
