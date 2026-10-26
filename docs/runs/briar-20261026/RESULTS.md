# Briar EHR conversion dress rehearsal — October 26, 2026

The autonomous rehearsal is complete. The explicitly authored source adapter loaded **3,036 resources across nine types** in **7.326 seconds**, with **0 target rejections**. Every one of **3,848 physical export rows** is accounted for. **65,052 clinical-field, identity, target-presence and disposition assertions** passed across 4 executed runs, listed below. These assertions are not independent tests or independent clinical validation.

**Operational result: completed with exceptions. Go-live result: NO-GO.** 75 records are held for unresolved source evidence, 79 depend on held records, and 40 observations are intentionally not loaded (withdrawn accessions or explicit no-result sentinels). No sign-offs were invented and no patients were merged. A deferred question is not a clinical answer and cannot release or drop its held records.

## What was actually built and executed

Briar is a new synthetic source, separate from Halcyon and Delphi: 320 registration charts at two formerly separate installations, fixed-width departmental files, local chart numbers, revisioned labs, a withdrawal journal, note continuations, medications, diagnoses, appointments and charges. Its 2018 dictionary is mostly right but contradicts a 2026 support note and several operational workflows. Five named simulated analysts have different knowledge and blind spots. There are 15 discovery questions and 12 runtime follow-ups in the evidence.

The stock Socratic builder generated a 91-rule declarative spec, provenance ledger, reader binding, Python profile and crosswalk CSVs. **The stock generated-reader path staged 3,848 source rows and loaded zero patients.** Its run correctly remains `staged`; the current implementation does not generate source-to-Nimbus domain mappers. I wrote an explicit test-scenario adapter using the discovered spec, then ran the ordinary Bridge Runner and embedded Nimbus **HTTP API contract**, including target validation, dependency checks, fidelity annotations, questions, counts, clinical sentinels and full loaded-record read-back. This was local embedded HTTP transport, not a remote-server/network test.

## The consequential disagreements

| Claim or conflict | What was checked | Conversion decision |
|---|---|---|
| Dictionary and systems: CHART is enterprise-wide. Registration: site-local. | 320 registrations, only 160 distinct CHART values; separate source installations; systems withdraws old assertion. | SITE+CHART identifies source charts; cross-site records remain separate. Matching demographics produce an identity-review question, never an automatic merge. |
| Systems uses a 1950 DOB pivot; registration proposes 1930. Dictionary says six-digit DOB. | 312 eight-digit dates, 5 blanks and 3 six-digit dates. No chart evidence for the legacy century. | Parse valid YYYYMMDD only. Hold all 8 uncertain birth dates; dependent resources wait. Neither analyst's preferred pivot becomes truth. |
| Lab supervisor: all Outreach glucose is now mmol/L; ignore unit labels. | B-site glucose rows still explicitly carry mg/dL, alongside mmol/L. These counts include historical revisions. Supervisor acknowledges residual devices. | Preserve transmitted units. Missing glucose units are held. No magnitude-based or site-wide unit conversion. |
| Dictionary: MED H is historical and may be skipped. Pharmacy: current H is on hold. | Pharmacy confirms the changed 3.7 workflow and refuses to attest to older versions. | Preserve current on-hold therapy; adapter rejects other delivery versions. Unmapped MISC drugs remain held with original name and sig archived. |
| Dictionary: all amounts are cents. Billing: Outreach changed to dollars. | A cents, B pre-cutover cents and B post-cutover decimal dollars all occur. Billing confirms service date, not extraction date, controls the change. | Preserve $125.50 across all three regimes. Quarantine credits rather than invert their signs. |
| NKA Y conflicts with positive allergy text. | 15 source conflicts; registration explains a sticky NKA flag. | Retain positive allergies and clear contradictory NKA on loaded patients. Allergies whose patients have unknown DOB remain blocked. |
| Numeric-only labs versus NEG, 999999 and comparator results. | Domain owner distinguishes a valid culture result, a missing-value sentinel and >600H-style measurements. | Preserve negative cultures, comparators and flags. Do not create a numeric 999999 observation. |
| Latest physical lab row versus latest revision; potassium delete versus entire accession. | Revision order is reversed; source journal and owner define whole-accession withdrawal. | Highest numeric revision wins. Withdraw every test on the accession; never resurrect its older revision. |
| APPT R means rescheduled versus possibly arrived. | No scheduling owner or status audit is available. | All 19 R appointments stay held. A convenient guess does not become a status map. |
| Full-width notes imply truncation. | Follow-up distinguishes continuation segments from upstream truncation; no original-length marker exists. | Reassemble by numeric SEQ, preserve indentation and delivered text; mark original completeness unverified. |
| Local times include 2400, 2461 and DST transition hours. | Both sites are Chicago local; support note defines midnight rollover but cannot establish DST offsets. | Normalize documented 2400 to next midnight; hold invalid, repeated and nonexistent wall-clock times. |

## Record accounting

| Resource | Logical records | Loaded | Held | Blocked | Dropped | Rejected |
|---|---:|---:|---:|---:|---:|---:|
| AllergyIntolerance | 30 | 29 | 0 | 1 | 0 | 0 |
| Appointment | 320 | 294 | 19 | 7 | 0 | 0 |
| ChargeItem | 320 | 288 | 12 | 20 | 0 | 0 |
| Condition | 320 | 312 | 0 | 8 | 0 | 0 |
| DocumentReference | 320 | 312 | 0 | 8 | 0 | 0 |
| Encounter | 320 | 299 | 14 | 7 | 0 | 0 |
| MedicationRequest | 320 | 299 | 14 | 7 | 0 | 0 |
| Observation | 960 | 891 | 8 | 21 | 40 | 0 |
| Patient | 320 | 312 | 8 | 0 | 0 | 0 |
| Total | 3230 | 3036 | 75 | 79 | 40 | 0 |

Physical rows and logical resources are different counts: 320 earlier glucose revisions are retained in the source archive, 640 note segments assemble into 320 documents, 8 journal rows withdraw accessions, and 30 registration rows also yield an allergy resource. The per-file/per-line accounting file links every physical row to its disposition and logical target. The 40 dropped observations comprise 24 withdrawn tests and 16 no-result sentinels after withdrawal precedence. None are silently discarded as unparsed input.

## Verification and repeated runs

| Run | Population | Purpose | Actual result |
|---|---:|---|---|
| Initial corrected run | 320 | End-to-end conversion | 3,036 loaded, zero rejected, full read-back and field/disposition grading pass |
| Fresh target, batch size 37 | 320 | Batch-order/replay sensitivity | Same clinical content and outcomes |
| Same target, repeat import | 320 | Idempotency | Same clinical content and outcomes; no new duplicate records |
| Second population, new seed | 160 | Reuse the same discovered 3.7 spec | 1,521 loaded; verification and field/disposition grading pass |

The stock verifier's default sentinels still depend on Halcyon-shaped source fields. The scenario adapter provides those explicit normalized aliases, and the separate source-specific grader checks actual Nimbus API snapshots for every logical record, every loaded patient's identity reference, dates, quantitative and qualitative results, revisions, comparators, units, flags, medication status and sig, diagnosis coding/text, allergy text, note bytes/order and charge scaling. This is stronger than checking only that a record was accepted, but it does not measure source capabilities absent from this fixture.

The discovery ledger replays to byte-identical spec/profile output, all analyst answers replay exactly, and re-profiling reproduces the recorded observations. A test also forbids grading-file reads during discovery and conversion. Seven fault-injection tests demonstrate that the grader rejects wrong units, lost comparators, stripped note indentation, active/on-hold swaps, wrong charge scaling, invented diagnosis coding and extra target records.

## Failures found during the rehearsal

1. **Native builder stops at staging.** Source-file bindings are working; general source-to-domain mapping and execution of generated semantic rules/known-unknowns are still missing. The explicit adapter is a demonstrated workaround, not evidence that the builder generated a complete ingestion.
2. **Generic fixed-width reader strips leading clinical whitespace.** `src/bridge/interview/reader.py:126` calls `.strip()` on every field. All 320 indented note continuations lose their indentation on the native path. The scenario reconstructs note content using the generated field spans and trims only right padding; all 312 loaded notes match the delivered segments exactly. Production reader behavior is unchanged by this PR.
3. **Read-back compares timestamp spellings literally.** `src/bridge/verify.py:37` considers equivalent UTC `+00:00` and `Z` strings unequal. The first adapter attempt was stopped with read-back alerts; a captured example confirms the instant did not change. The adapter now emits Nimbus's canonical UTC `Z` representation. The original failed-attempt log is preserved separately; no alert was waived to force a pass.

These findings should become product work: generate/validate domain mappings and enforce known-unknown routing; support per-field whitespace semantics; compare typed timestamps semantically; make clinical sentinel definitions source-specific. Unavailable clinical facts remain a source-operations problem, not something a converter can safely invent.

## What remains unresolved

There are 11 blocking question groups covering missing/ambiguous DOB, invalid/DST times, unverified glucose units, unmapped medications, source credits and APPT R. A nonblocking identity group covers two charts with matching demographics, retained separately. Runtime follow-up questions were sent through the same simulated-analyst ask interface; without additional chart evidence, those answers stay unknown and release no records. Fidelity losses or explicitly unverified assumptions also await owner sign-off. The run's NO-GO is intentional and supported by the unresolved records, not a stopped or unfinished execution.

## Limits of this evidence

The same assistant authored the source fixture, analysts, interview and adapter. This is **not a blinded test** of discovery, and its success rate is not an independent estimate of real-world import quality. Analysts use deterministic recorded answers through `AnalystService.ask`, not independent live models or actual staff. Grading truth is kept out of the conversion code path and consulted only by the separate scoring step after snapshots are written, but the fixture author already knows what was planted. A genuinely blinded follow-up needs an independently authored estate and independently supplied analyst backend. The second population changes the seed and size, not the source's underlying error families. The scenario preserves source charge-to-visit references but does not validate service-date consistency against encounter dates; source-era billing dates therefore need a separate revenue-cycle audit. No claim is made about production scale, network faults, live incremental cutover, real clinical terminology validity or real-world go-live readiness.

## Reproduce

Tested base: `8175d7eb0026012e7174121b35e2a15b6a76e6e4` plus this task branch. Python 3.12; existing project dependencies; no added dependency or remote LLM calls.

```bash
python -m pip install -e '.[dev]'
python -m testbed.scenarios.briar --out runs/briar-new --patients 320 --seed 2626
python -m pytest -q
```

The output contains source files and private grading truth, frozen discovery and full runtime ledgers, generated spec/profile/binding/crosswalks, per-field profiling evidence, source-row accounting, target API snapshots, record outcomes, read-back/readiness reports, HTML reports, SHA-256 evidence hashes, repeated-run comparisons and computed grades. Output directories must be fresh; prior evidence is never overwritten.

## Recorded evidence

- [Discovery dialogue](INTERVIEW.md)
- [Runtime analyst questions and responses](runtime-interviews.json)
- [Source measurements](evidence.json)
- [Native staging result](native-staging.json)
- [Conversion, full read-back and readiness](conversion-results.json)
- [Computed grades across four runs](grades.json)
- [Replay checks](replay-checks.json)
- [Initial timestamp-spelling failure](first-attempt-failure.txt)
- [Local pytest output](pytest.txt)
- [Full source and run-evidence archive](evidence.zip)

Local verification: 797 tests passed in 176.41 seconds. The 18 Briar acceptance cases include seven clinical fault injections, grading-read isolation, deferral safety, committed-ledger re-profiling and actual stock-reader dispatch.
