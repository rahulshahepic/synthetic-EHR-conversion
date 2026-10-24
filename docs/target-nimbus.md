# Target EHR: Nimbus (invented)

Nimbus is a fictional modern, API-first EHR. Its model is FHIR-*inspired* but deliberately **not** FHIR, and not a superset of Halcyon: some Halcyon concepts have no home (fidelity loss), and some Nimbus fields are required but absent in Halcyon (must be derived, defaulted, or asked about).

Code: `src/nimbus/` — `models.py` (pydantic contracts), `validation.py`, `store.py` (SQLite), `api.py` (FastAPI). Run: `python -m nimbus serve --db nimbus.db --port 8700`.

## Resource types and notable rules
Every resource has: `id` (Nimbus UUID), `sourceKey` (unique per resource type; idempotency key from importer), `provenance` (`{importBatchId, importedAt, system}`), `meta.version`.

| Resource | Required / strict rules that create conversion pressure |
|---|---|
| `Organization` | 3-level: `type` ∈ `system, site, department`; `partOf` required below `system`. |
| `Location` | Must belong to a `department`. |
| `Practitioner` | `name {family, given[], suffix[]}`; `npi` 10-digit Luhn-valid **required if `billing=true`**; `specialty` from Nimbus specialty enum (~30 values). |
| `Patient` | `identifiers[]` (`system`, `value`), **one** enterprise identity per person; `name {family, given[]}`; `birthDate` full ISO date **required**; `sexAtBirth` ∈ `female, male, unknown`; `genderIdentity` optional enum; `address[]` structured; `telecom[]` E.164 phones; `race[]`/`ethnicity` from OMB enum or `asked-declined`/`unknown`. Supports `POST /patients/{id}/$merge`. |
| `Coverage` | `payerId`, `planId`, `subscriberRelationship` ∈ `self, spouse, child, other`; `order` unique per patient+period. |
| `Encounter` | `class` ∈ `ambulatory, emergency, inpatient, observation, virtual`; `period.start` with **timezone** required; `period.end` required when `status=finished` and class=inpatient. |
| `Condition` | `code` must be `ICD-10-CM` or `SNOMED-CT` (no ICD-9, no local); `clinicalStatus` ∈ `active, inactive, resolved`. Free-text-only allowed only as `verificationStatus=unconfirmed` with `code.text`. |
| `AllergyIntolerance` | `substance` coded (RxNorm/SNOMED) or `{text}` with `codingStatus=uncoded`; `reactions[]` each SNOMED or text; `criticality` ∈ `low, high, unable-to-assess`. "No known allergies" is a **patient-level flag**, not a row, and conflicts are rejected. |
| `MedicationRequest` | `medication` RxNorm required; structured `dosage {doseQuantity{value,unit(UCUM)}, route, frequency{count, periodUnit}, asNeeded, durationDays}`; `dosage.text` allowed only with `dosageStructured=false`. |
| `Observation` | `category` ∈ `laboratory, vital-signs`; `code` LOINC **required**; value one of `valueQuantity{value, unit(UCUM), comparator}`, `valueCodeable`, `valueString`; `referenceRange{low, high}` numeric; physiologic plausibility limits for vitals (rejects weight > 1000 kg etc.). BP is one Observation with two components. |
| `Immunization` | `vaccine` CVX required; `occurrenceDate` required. |
| `DocumentReference` | `content` as markdown or plain text (no RTF); max 1 MB; `type` LOINC document code. |
| `Appointment` | `status` ∈ `proposed, booked, arrived, fulfilled, cancelled, noshow`; participant references. |
| `ChargeItem` | `code` CPT/HCPCS; `modifiers[]` (2-char, max 4); `amount` decimal USD; `encounterId` required. |
| `UserAccount` | No shared/generic accounts allowed (must map to a person or be dropped). |

## Import API (v1)
All JSON. Errors use `{code, message, field, severity}` with stable codes (e.g. `E_REQUIRED`, `E_CODE_SYSTEM`, `E_REF_UNRESOLVED`, `E_PLAUSIBILITY`, `E_CONFLICT`, `W_TRUNCATED`).

| Method & path | Purpose |
|---|---|
| `GET /api/v1/meta/schema` | JSON Schemas for each resource (lets importers validate locally). |
| `GET /api/v1/meta/valuesets/{name}` | Enumerations (specialties, races, ...). |
| `POST /api/v1/import/batches` | `{resourceType, externalBatchId, mode: "commit" \| "validate-only"}` → `batchId`. |
| `POST /api/v1/import/batches/{batchId}/records` | Up to 500 records `[{sourceKey, resource}]`. Returns per-record `accepted \| rejected` + `targetId` + issues. Upsert by `sourceKey` (idempotent). |
| `POST /api/v1/import/batches/{batchId}/close` | Finalize; returns counts. |
| `GET /api/v1/import/batches/{batchId}` | Status and counts. |
| `POST /api/v1/import/batches/{batchId}/rollback` | Deletes/restores every record written by that batch (restores prior version for upserts). Refuses (409) if a later, non-rolled-back batch references those records unless `cascade=true`. |
| `GET /api/v1/{resourceType}/{id}` / `GET /api/v1/{resourceType}?sourceKey=...&identifier=...&patient=...` | Read-back for verification. |
| `GET /api/v1/{resourceType}/$count` | Counts for reconciliation. |
| `POST /api/v1/patients/{id}/$merge` | `{sourcePatientId}` – moves clinical data, marks source inactive. |

### References
Resources reference others either by Nimbus id (`{"id": "..."}`) or by importer key (`{"sourceKey": "Patient/H-FAC1-000123"}`); Nimbus resolves `sourceKey` references at write time and rejects `E_REF_UNRESOLVED` if absent. Bridge prefers `sourceKey` references so rollback/re-load stays deterministic.
