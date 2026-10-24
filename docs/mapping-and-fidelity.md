# Mapping and Fidelity

The two models do not line up. Bridge must make every lossy decision **explicit, measured, and reviewable**.

## Fidelity annotations
Each mapper annotates every target field it writes (and every source field it consumes or ignores) with one class:

| Class | Meaning | Example |
|---|---|---|
| `exact` | Value copied with no semantic change | MRN → identifier.value |
| `transformed` | Lossless format change | `19840312` → `1984-03-12`; `"LAST,FIRST"` → structured name |
| `standardized` | Mapped to a standard code via a deterministic crosswalk with 1:1 meaning | local `GLU` → LOINC `2345-7` |
| `inferred` | Derived by rule/heuristic; plausible but could be wrong | lb vs kg from facility; time zone from facility; site org inferred from dept |
| `degraded` | Kept, but with less structure/meaning | unparseable sig → `dosage.text`; uncoded allergen as text; RTF → plain text |
| `defaulted` | Required target field absent; policy default applied | `sexAtBirth=unknown` |
| `dropped` | Source data with no target home | appointment status `B` (bumped) history; Halcyon note formatting; secondary COB duplicates |
| `held` | Not loaded pending a reconciliation answer | ICD-9 code with 3 candidate ICD-10 targets |

**Record fidelity score** = weighted mean over fields (`exact/transformed/standardized`=1.0, `inferred`=0.8, `degraded`=0.5, `defaulted`=0.3, `dropped`=0). Weights per field are declared per mapper (e.g. allergy substance ≫ note font). Aggregated per resource type, per batch, and per run.

Every dropped/degraded datum is also written to a **loss ledger** (`run_id, source_key, field, original_value, reason`) that can be exported and attached to the converted chart as a "legacy data" DocumentReference if policy says so (configurable per domain).

## Decision policies
For each ambiguity class, a policy says what Bridge does without a human:
- `hold` – don't load the record; open a question (default for clinically significant: allergies, meds, active problems, merges).
- `best_effort` – load with the best guess, annotate `inferred`, open a non-blocking question.
- `degrade` – load as text/uncoded, annotate `degraded`.
- `drop` – write to loss ledger only.

Answers to questions become **mapping rules** (`scope`: this record / this source code / this pattern) stored in the run DB and versioned; rules are applied on re-processing and future runs.

## Key mapping problems (the "hard parts")
1. **Identity**: per-facility MRNs → one enterprise Patient. Deterministic match (same SSN-last-4 + DOB + normalized name) auto-links; probabilistic matches above threshold → question; ADT A40 merges honored.
2. **Organization hierarchy**: 2-level → 3-level (infer `site` from facility, shared depts duplicated per site with `inferred`).
3. **Terminology**: ICD-9→ICD-10 (GEM-like crosswalk with 1:many), local lab→LOINC, local formulary→RxNorm, local vaccine→CVX, specialties → Nimbus enum, CPT/local charge codes.
4. **Units & values**: non-UCUM units, comparators in strings, unit-less temps/weights, plausibility checks.
5. **Structure**: free-text sigs → structured dosage; concatenated reactions/modifiers/addresses; BP string → components.
6. **Time**: zone-less local timestamps → zoned, with DST ambiguity flagged.
7. **Status vocabularies**: visit, appointment, problem, coverage-relationship enums that don't align (e.g. appointment `B`).
8. **Conflicts across channels**: DB vs HL7 vs CSV precedence; conflicting NKA vs allergy rows.
9. **Unrepresentable data**: generic user accounts, truncated notes, retired codes.

Crosswalk tables live in `src/bridge/terminology/data/*.csv` (synthetic, small, invented codes where real standards would be licensed — clearly labeled).
