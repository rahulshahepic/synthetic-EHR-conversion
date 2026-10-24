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

### Phase 2 — rehearsals, cutover, operations
Real conversions run several *rehearsal* conversions, then a final *cutover* with a delta load. Phase 2 makes Bridge do that.

| # | Milestone | Branch | Owner | Exit criteria |
|---|---|---|---|---|
| M7 | **Rehearsals**: carry answered rules from a prior run (`run --rules-from <run.db>` / `rules export|import` JSON); run-vs-run comparison report (metrics, question counts, fidelity per type) | `claude/m7-*` | Claude | Second rehearsal on the same export asks zero already-answered questions; comparison shows the delta |
| M8 | **Cutover delta**: export mutator (T-111) produces "export B" = A + new/changed/deleted records; Bridge delta run against the same Nimbus: created / updated / unchanged per type; records present in the prior run but gone from the source become `source_deleted` questions (never silent deletes) | `claude/m8-*`, `task/T-111` | Claude + helper | Delta run on B touches only changed records; deletions surface as questions |
| M9 | **Late identity merges**: an identity question answered "same" after both patients loaded uses Nimbus `$merge`, relinks Bridge xrefs, and is revertible | `claude/m9-*` | Claude | Test: load both, answer same, Nimbus has one active patient with all clinical data |
| M10 | **Demo scenario**: `python -m testbed.demo` runs a scripted end-to-end conversion with a simulated user answering questions, producing a narrated transcript and the run report (T-106) | `claude/m10-*` | Claude | One command shows the whole story |

Stretch: web dashboard for runs; second source profile (e.g. a facility with metric units and different conventions) to exercise drift monitors; performance at 50k patients.

## Status
See `TASKS.md` for live task-level status. Milestone status is updated in this table's companion section below on each merge.

- M0: done
- M1: done (Nimbus service, 19 API tests)
- M2: done (Halcyon generator; 500 patients ≈ 30k rows + feeds in <1s; ~40 planted issue types)
- M3: done (Bridge core: identity, metrics/monitors, pause/answer/resume, revert, CLI)
- M4: done (all 17 Nimbus resource types; ORU/SIU/registry channels; 500 patients ≈ 26s)
- M5: done (MCP server over stdio with 20 tools + docs resources; server-side guards for clinical answers and revert)
- M6: done (verification: count reconciliation, read-back sampling, clinical sentinels)
- M7: done (rules carry over via `run --rules-from <run.db|rules.json>`; `rules-export`; `compare --other-run-db`; MCP `compare_runs`)
- M8: in progress
