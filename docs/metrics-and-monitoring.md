# Metrics, Monitoring, Pause and Revert

## Metrics (computed per batch, rolled up per resource type and per run)
| Metric | Definition | Why |
|---|---|---|
| `extracted` / `mapped` / `held` / `map_rejected` / `load_accepted` / `load_rejected` | Counts at each stage | Funnel; nothing silently disappears (`extracted = loaded + held + rejected + dropped_by_policy`, checked as an invariant). |
| `target_reject_rate` | `load_rejected / attempted` | Contract mismatch or bad mapping. |
| `hold_rate` | `held / mapped_attempted` | Ambiguity volume → human workload. |
| `fidelity_score` | Mean record fidelity (see mapping doc) | Quality of what landed. |
| `loss_rate_by_field` | Share of records with `degraded/dropped/defaulted` per field | Pinpoints where fidelity leaks. |
| `code_coverage` | Share of coded fields mapped to a standard system (by code system) | Terminology gaps. |
| `ref_resolution_rate` | Resolved references / total references | Ordering or identity bugs. |
| `identity_match_stats` | auto-linked, queued, new persons | EMPI behavior. |
| `count_reconciliation` | Source vs Nimbus `$count` per type (after expected exclusions) | End-to-end completeness. |
| `readback_mismatch_rate` | Sampled read-back fields that differ from mapped payload | Detects silent target-side transforms. |
| `clinical_sentinels` | Must-match counts: patients with ≥1 active allergy; active anticoagulant / insulin orders; abnormal-flag critical labs; active problems per patient (distribution) | Patient-safety guardrails; loss here is never acceptable silently. |
| `throughput`, `latency_p95` | Records/s, API latency | Operational. |

## Monitors
Evaluated after every batch (`bridge/monitor/rules.py`, configurable YAML-free Python defaults overridable by `bridge.toml`):

- **Absolute thresholds** (per resource type): e.g. `target_reject_rate > 2%` → PAUSE; `hold_rate > 15%` → PAUSE; `fidelity_score < 0.85` → WARN, `< 0.7` → PAUSE; any `clinical_sentinel` delta ≠ 0 → PAUSE.
- **Drift vs baseline**: after ≥3 batches of a type, a metric more than `k·σ` (default k=3) from the run's rolling baseline → WARN (or PAUSE for reject/hold rates). Catches "batch 37 suddenly lost all its units" (e.g. a facility with different conventions).
- **Invariants**: funnel accounting broken, or a reference resolution rate < 100% for committed records → PAUSE immediately.

Each alert records: `metric, scope (run/type/batch), observed, threshold_or_baseline, severity, sample_source_keys[], suggested_actions[]`.

## Pause / resume
On PAUSE the runner finishes the in-flight API call, closes the batch, persists state, and stops. Operators (or an AI assistant via MCP, with user consent) can inspect alerts, answer questions, add mapping rules, then:
- `resume` – continue from the next batch,
- `reprocess --batch <id>` – roll back and redo one batch with current rules,
- `revert` – see below,
- `acknowledge <alert>` – accept and continue (recorded with who/why).

## Revert
- Every Nimbus write is tagged with Bridge's batch id. Bridge's run DB keeps the batch ledger (`batch_id, resource_type, nimbus_batch_id, status, source_keys`).
- `revert --batch X`, `revert --type Observation`, `revert --run` call Nimbus rollback in **reverse dependency order**, then verify `$count` returns to its pre-batch value.
- Reverts are themselves logged and are idempotent.

## End-of-run verification (`src/bridge/verify.py`)
Runs automatically when a pass finishes (and on demand: CLI `verify`, MCP `verify_run`). Any failure pauses the run with a `pause` alert.
- **Count reconciliation**: for every type, Nimbus `$count` == Bridge `loaded`, and staged == loaded + dropped + superseded + held + blocked + rejected + pending.
- **Read-back sampling**: 25 random loaded records per type are fetched from Nimbus and compared field by field with what Bridge sent (references compared by `sourceKey`; fields Nimbus adds are ignored).
- **Clinical sentinels**: active anticoagulant orders, active insulin orders, distinct patients with ≥1 real allergy, abnormal-flagged labs. Each source item must be in Nimbus with the same clinical meaning, or be explained by a record status (held, dropped, ...). An unexplained delta is a patient-safety finding — the test suite plants a mapping bug that silently marks warfarin/apixaban orders completed, and verification catches it although Nimbus accepted every record.

## Rehearsals and cutover (M7, M8)
- `run --rules-from <prior run.db | rules.json>`: reuse every answered question (identity merges applied up front).
- `compare --other-run-db <prior>`: pauses, questions, alerts, per-type counts and fidelity, rehearsal vs rehearsal.
- `run --prior-run <prior run.db>`: cutover delta against the prior run's Nimbus. Unchanged records are no-op upserts; the batch metrics count `created / updated / unchanged`. Records loaded before but absent from the new source are staged as `_retire` records and raise one `source_deleted` question per type (default *keep*; *retire* marks Conditions entered-in-error, meds stopped, encounters/appointments/observations cancelled). Bridge never deletes silently. Canonical-duplicate choices (`dedupe`, COB order) are inherited from the prior run so the delta never flips them.

## Go-live readiness (M13, `src/bridge/readiness.py`)
`readiness` (CLI / MCP) returns **GO** only when: the run finished; no blocking questions; every record resolved (no held, blocked, rejected or pending); every pause alert acknowledged by a named user; verification green; and the fidelity loss of every affected resource type signed off by a named owner (`signoff --domain Observation --by user:lab-director`). A sign-off goes stale if the loss changes afterwards. Warnings (not blocking): answers given by the assistant, and unreviewed non-blocking questions.
