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
