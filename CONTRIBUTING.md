# Contributing (humans and AI agents: Claude, ChatGPT, Muse, ...)

Several AI agents work in this repo concurrently without talking to each other. These rules keep that safe.

## Workflow
1. **Read first**: `README.md`, `docs/ARCHITECTURE.md`, and the doc(s) for the area you touch.
2. **Pick a task** from `TASKS.md` whose status is `ready`.
3. **Claim it** by creating and pushing a branch named exactly `task/<ID>-<short-slug>` (e.g. `task/T-102-sig-parser`) from the latest `main`. Before claiming, check the remote branches (`git fetch origin && git branch -r | grep task/<ID>`): **if a branch for that ID already exists, the task is taken — pick another.**
4. In your branch, first commit: change the task's status in `TASKS.md` to `in-progress (<agent name>)`.
5. Do the work. Stay inside the files listed for the task; if you must touch other files, keep it minimal and explain why in the PR.
6. Run `python -m pytest` — all tests must pass. Add tests for what you build (the task's acceptance criteria are the minimum).
7. Open a PR into `main` titled `<ID>: <title>`. Set the task status to `review` in `TASKS.md`. Describe what you did, what you didn't, and any open questions.
8. Never push directly to `main`. Never force-push someone else's branch. Never rewrite `main` history.

Branch prefixes: `claude/*` (Claude's milestone branches), `task/*` (claimed tasks, any agent).

## Ground rules
- **Boundaries** (`tests/test_boundaries.py` enforces): `src/bridge` must not import `testbed` or `nimbus`; `src/nimbus` must not import `bridge` or `testbed`. Bridge reaches Nimbus only through `bridge.load.client`.
- **Bridge must never read `answer_key/`** from a Halcyon export.
- All data is synthetic. Never add real patient data, real people's names tied to clinical data, or licensed code content (real CPT descriptors, full SNOMED/LOINC tables). Small invented or public-domain-ish code samples are fine and must be labeled synthetic.
- Python 3.12+, type hints, stdlib + deps in `pyproject.toml`. Ask (in the PR) before adding a dependency.
- Deterministic tests: seed every random generator.
- Keep functions pure where possible; mapping code must emit fidelity annotations for every field it writes.

## Setup
```
pip install -e ".[dev]"
python -m pytest
```
