# Plan and Milestones

Goal: a convincing, honest proof-of-concept of converting a messy legacy EHR (Halcyon) into a modern one (Nimbus), with measured fidelity, safety monitors that pause the run, full revert, and an AI-assistable reconciliation loop.

Each milestone ends with a merge of its branch into `main` with passing tests (`pytest`).

| # | Milestone | Branch | Owner | Exit criteria |
|---|---|---|---|---|
| M0 | Plans, contracts, task board | `claude/plan-architecture` | Claude | Docs + TASKS.md on main |
| M1 | **Nimbus** target EHR: models, validation, SQLite store, import API with batches, upsert-by-sourceKey, rollback, read/count endpoints | `claude/m1-nimbus` | Claude | API tests: accept/reject/upsert/rollback/cascade-refusal |
| M2 | **Halcyon** testbed generator: DB + HL7 + CSV, planted issues, answer key | `claude/m2-halcyon` | Claude | Deterministic for a seed; answer key lists every planted issue |
| M3 | **Bridge core**: run DB, DB extractor, mapping framework with fidelity + questions, loader, metrics, monitors, pause/resume, revert, CLI; mappers for Organization, Location, Practitioner, Patient (identity), Coverage, Encounter, Condition, AllergyIntolerance | `claude/m3-bridge-core` | Claude | End-to-end run on seed 42 with metrics; forced-breach test pauses; revert restores counts |
| M4 | Remaining domains + channels: MedicationRequest, Observation (labs, vitals), Immunization, DocumentReference, Appointment, ChargeItem; HL7 + CSV extractors with channel precedence | `claude/m4-*`, `task/*` | Claude + helpers | All domains load; count reconciliation explains every delta |
| M5 | **MCP server** + question/answer → rule → reprocess loop | `claude/m5-mcp` | Claude | MCP tool tests; answering a grouped question releases held records |
| M6 | Verification & reporting: read-back sampling, clinical sentinels, loss report, run report (HTML/Markdown), detection-recall test vs answer key | `claude/m6-*`, `task/*` | Claude + helpers | Report generated; recall thresholds asserted in tests |

Stretch: web dashboard for runs; second source profile (e.g. a facility with metric units and different conventions) to exercise drift monitors; performance at 50k patients.

## Status
See `TASKS.md` for live task-level status. Milestone status is updated in this table's companion section below on each merge.

- M0: done
- M1: done (Nimbus service, 19 API tests)
- M2: done (Halcyon generator; 500 patients ≈ 30k rows + feeds in <1s; ~40 planted issue types)
- M4: done (all 17 Nimbus resource types; ORU/SIU/registry channels; 500 patients ≈ 26s)
- M3: done (Bridge core: 10 resource types, identity, metrics/monitors, pause/answer/resume, revert, CLI; 500-patient run ≈ 8s)
