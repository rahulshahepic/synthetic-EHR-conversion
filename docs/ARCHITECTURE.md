# Architecture

Proof-of-concept EHR data conversion. Everything here is synthetic: both EHRs are invented.

| Component | What it is | Location | May import from |
|---|---|---|---|
| **Halcyon** | Invented *legacy source* EHR. Test fixture only: a seeded generator that writes a Halcyon export (SQLite DB + HL7 v2 feeds + CSV extracts) with realistic data-quality problems planted on purpose. | `testbed/halcyon/` | stdlib only |
| **Nimbus** | Invented *modern target* EHR. A small service with its own data model, validation rules, storage and versioned bulk-import REST API. | `src/nimbus/` | itself |
| **Bridge** | The conversion application (the actual product). Extract → map → validate → load, with metrics, monitors, pause/resume, revert, and a reconciliation question queue exposed to AI chatbots over MCP. | `src/bridge/` | itself; talks to Nimbus **only through its API client** |

Hard boundaries (enforced by `tests/test_boundaries.py`):
- `bridge` never imports `testbed` or `nimbus` internals. It reads Halcyon only from export files on disk, and writes Nimbus only via `bridge.load.client` (HTTP or in-process adapter speaking the same API contract).
- `nimbus` never imports `bridge` or `testbed`.
- `testbed` never imports `bridge` or `nimbus` (except `testbed/scenarios` end-to-end harnesses).

## Pipeline

```
 Halcyon export dir                         Bridge                                   Nimbus
 ├─ halcyon.db (SQLite) ─┐                                                       
 ├─ feeds/*.hl7 ─────────┼─► extract ─► stage ─► map ─► validate ─► load ───────►  /api/v1/import/...
 └─ extracts/*.csv ──────┘   (readers)  (raw     (per-   (local    (batched,         batches, records,
                                         rows +   domain  pre-check  idempotent       commit, rollback
                                         lineage) mappers) vs Nimbus  by sourceKey)
                                                  │       contract)    │
                                                  ▼                    ▼
                                         questions queue ◄──── metrics + monitors ──► pause / alert
                                                  │                    │
                                                  ▼                    ▼
                                           MCP server  ◄──── AI chatbot ◄──► human user
                                                                       │
                                                       revert (batch / domain / run)
```

### Stages
1. **Extract** – readers for each Halcyon channel produce `SourceRecord(domain, source_key, payload, channel, lineage)`. HL7 and DB can describe the same entity; extract reconciles channel precedence (documented in `mapping-and-fidelity.md`).
2. **Stage** – raw records are persisted in Bridge's run DB (`bridge_run.db`, SQLite) so every downstream decision is replayable and explainable.
3. **Map** – one mapper per target resource type. Each mapper returns a `MapResult`: target payload, per-field **fidelity annotations**, warnings, and zero or more **reconciliation questions**. Records whose questions block loading are held (`HELD`) instead of guessed.
4. **Validate** – local contract check against the Nimbus schema (fast fail before a network call). Nimbus remains the authority; it re-validates.
5. **Load** – dependency-ordered, batched calls to the Nimbus import API. Every record carries a deterministic `sourceKey` (idempotent re-load) and every batch carries Bridge's run/batch id as provenance (enables rollback).
6. **Verify** – read-back sampling: fetch loaded records from Nimbus and compare against the mapped payload and against source sentinels.

### Load order (reference dependencies)
`Organization → Location → Practitioner → Payer/Plan → Patient → Coverage → Encounter → Condition, AllergyIntolerance, MedicationRequest, Observation, Immunization, DocumentReference → Appointment → ChargeItem`

### Run control
A **run** is a conversion of one Halcyon export. It is split into **batches** (default 250 records, per resource type). After every batch the monitor evaluates metrics; a breach moves the run to `PAUSED` with an alert explaining which metric, the observed value, the threshold/baseline, and sample offending records. A paused run can be:
- `resume`d (optionally after answering questions / adding mapping rules),
- `reprocess`ed for the held/failed subset only,
- `revert`ed — a batch, a resource type, or the whole run — via Nimbus `POST /api/v1/import/batches/{id}/rollback`, in reverse dependency order.

State machine: `CREATED → EXTRACTING → RUNNING ⇄ PAUSED → COMPLETED | ABORTED`, plus `REVERTING → REVERTED`.

## Tech
Python 3.12+, FastAPI (Nimbus API), SQLite (all storage), pydantic v2 (contracts), pytest, `mcp` Python SDK v2 (`mcp.server.mcpserver.MCPServer`) for the AI interface. CLI via `argparse` (`python -m bridge ...`). No external network needed; everything runs on a local checkout.
