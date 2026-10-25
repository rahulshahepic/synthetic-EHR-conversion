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
- [Source: Delphi](docs/delphi.md)
- [Target: Nimbus & import API](docs/target-nimbus.md)
- [Mapping & fidelity](docs/mapping-and-fidelity.md)
- [Metrics, monitoring, pause & revert](docs/metrics-and-monitoring.md)
- [Reconciliation & AI (MCP)](docs/reconciliation-and-ai.md)

## Chat with the demo (no local setup)
The repo is wired so an AI coding agent can run a conversion *with you*: it starts the run, puts each decision to you in
plain language, records your answer under your name, resumes, and explains the results. Instructions for agents are in
[`AGENTS.md`](AGENTS.md).

| Assistant | How |
|---|---|
| **Claude Code on the web** (claude.ai/code, works on a phone) | Start a session on this repo and say: *"Run the guided conversion demo with me."* The `bridge` MCP tools are preconfigured (`.mcp.json`, installed by `scripts/session-start.sh`). |
| **ChatGPT → Codex** (chatgpt.com/codex) | Start a task on this repo: *"Follow AGENTS.md: run the guided conversion demo and ask me each decision."* Codex drives the CLI (`python3 -m bridge ... next / answer / resume`). Reply to each question in the task thread. |
| **Muse / any agent with a shell** | Same prompt as Codex; `AGENTS.md` has the full playbook. |

## See the runs on GitHub (no local setup)
**Demo site:** https://rahulshahepic.github.io/synthetic-EHR-conversion/ lists up to 20 successful demo runs, preserving the newest `main` run. Each report has a stable URL under `runs/<branch-slug>/<actions-run-id>-<attempt>/`; the index links to the newest `main` run. `branches/<branch-slug>/` redirects to the latest retained run for that branch. Reports outside the retained 20 are removed from Pages, though Actions artifacts follow their own retention period. The first publication creates an archival `gh-pages` branch; keep **Settings → Pages → Build and deployment → Source** set to **GitHub Actions**. GitHub Actions needs permission to write repository contents so the workflow can update that branch (in **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions** if the archive job receives a 403). If the `github-pages` environment restricts deployment branches, allow the branches from which you manually run this workflow.

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
