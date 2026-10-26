# Meridian: Socratic interview and end-to-end conversion results

A third synthetic source system ([Meridian](meridian.md)) was built to be messy the way real estates
are, then interviewed with the Socratic import builder and converted into Nimbus through the spec that
interview generated. The result was graded against the answer key. In Meridian, the vendor guide is mostly
right but aged, and right for old data where it is wrong for new. The analysts are right about their own
corner, sometimes only partly, sometimes plainly wrong, and they disagree. Conventions changed over time
and differ by campus.

Reproduce: `python -m testbed.meridian.demo --out demo_meridian` (about 3 seconds).

## Read this first: what this does and does not prove

- **The interview was not blind.** The same agent (Claude) built Meridian, wrote the analyst profiles, ran
  the interview and role-played the analysts. The firewall held mechanically (estate documents only through
  `read_estate`; the answer key and profiles were refused when tried), but the interviewer knew the planted
  problems from writing them. The scorecard measures whether the *pipeline* carries each fact through
  correctly, not how good an interviewer is at finding what it doesn't already know. A blind run needs a
  separate analyst backend.
- **The analysts answered in character.** Each answer follows only what that analyst's profile knows,
  including the wrong beliefs. Ray, for example, still insists lab timestamps are always Oracle-style when
  shown the other format. Runtime answers are attributed to `sim-analyst:<name>`, never to a real user,
  and none was taken from the answer key.
- **Go-live readiness is NO-GO on purpose.** It needs named humans to acknowledge alerts and sign off on
  fidelity loss. That was left for a human.

## The interview (ledger `src/bridge/interview/ledgers/meridian.jsonl`, 414 events)

1. **Estate documents.** Read the memo, manifest and guide. The guide (v3.2, format 3.x) is older than the
   extract (4.0).
2. **Profiling.** 117 field observations, including value distributions and *format signatures* (the
   shapes values take: `99-AAA-99 99:99` vs `9999-99-99 99:99`). Mixed shapes inside one field are how a
   convention change shows up in data. The profiler contradicted or extended the guide on 10 fields.
3. **Cross-tabs before the interviews,** to find *where* each mixed convention lives:
   - ISO lab timestamps appear only at Sun Ridge from 2024 on.
   - Dotted ICD codes appear only before 2012.
   - Relationship `D` appears only on Sun Ridge coverages that started before March 2016.
   - Sun Ridge's blank-unit vitals all date from before March 2016, with temperatures of 97–100.
   - 11 VOID visits are ER visits from 2018 on that have vitals.
   - HOLD orders never have a stop date.
   - MD0108's RxNorm disagrees with the reference code.
4. **Interviews.** 37 questions to the 4 analysts, each specific to the cross-tab findings.
5. **Resolutions.** 18 resolutions, each citing its evidence, and several deliberately combining sources:
   - **Both right, in different periods:**
     - ICD codes: the guide for pre-2012 rows, Denise for later ones.
     - Relationship codes: Denise for current codes, the guide's `D` for migrated Sun Ridge rows.
     - Lab timestamps: Ray for 91% of rows, the guide's format for Sun Ridge since 2024.
   - **Analyst over the guide:** time zones (Gary); VOID visits (Denise, whose triage-vitals criterion
     the data supports).
   - **Guide over the analyst:** HOLD orders (the guide, against Priya).
   - **A reference check over the analyst's memory:** MD0108's RxNorm.
   - **Hedged analyst plus data:** migrated Sun Ridge units. Gary "thinks" the old system was in American
     units; the 97–100 temperatures support him.
6. **One question left open on purpose.** Nobody knew what appointment status `BMP` means, so it routes
   to a runtime question.
7. **Honesty revision.** The first canonical binding gave migrated Sun Ridge vitals a unit the source
   never had. Bridge would have recorded that as read from the source. The binding was revised (on the
   ledger) so that values the spec derives are annotated as *inferred*.
8. **Spec.** 166 rules (118 data-confirmed); checklist 139 covered, 1 disputed, 0 open.

## Interview scorecard
| Entry | Kind | Verdict | How |
|---|---|---|---|
| guide_version_skew | dictionary | caught-by-dictionary | spec R010 (dictionary, data_confirmed=False) |
| guide_timezone | dictionary | caught-by-analyst | spec R146 (analyst, data_confirmed=True) |
| guide_dx_decimal_partial | dictionary-partial | caught-by-analyst | spec R080 (analyst, data_confirmed=True) |
| guide_sex_codes_aged | dictionary-aged | caught-by-analyst | spec R074 (analyst, data_confirmed=True) |
| guide_rel_codes_partial | dictionary-partial | caught-by-interviewer | spec R043 (interviewer, data_confirmed=True) |
| guide_visit_types_aged | dictionary-aged | caught-by-analyst | spec R119 (analyst, data_confirmed=True) |
| guide_void_partial | dictionary-partial | caught-by-analyst | spec R117 (analyst, data_confirmed=True) |
| guide_lab_timestamp_partial | dictionary-partial | caught-by-interviewer | spec R050 (interviewer, data_confirmed=True) |
| guide_result_status_aged | dictionary-aged | caught-by-analyst | spec R054 (analyst, data_confirmed=True) |
| guide_appt_status_aged | dictionary-aged | routed-to-runtime-question | known unknown in the spec |
| guide_stale_immune | dictionary | caught-by-dictionary | spec R133 (dictionary, data_confirmed=False) |
| guide_hold_right | dictionary-right | caught-by-dictionary | spec R095 (dictionary, data_confirmed=True) |
| undocumented_placeholder_dob | dictionary | caught-by-analyst | spec R061 (analyst, data_confirmed=True) |
| drugfile_wrong_rxnorm | reference-data | caught-by-interviewer | spec R002 (interviewer, data_confirmed=False) |
| belief_mpi_no_duplicates | analyst-belief | caught-by-analyst | spec R144 (analyst, data_confirmed=False) |
| belief_cancelled_results_purged | analyst-belief | caught-by-analyst | spec R054 (analyst, data_confirmed=True) |
| partial_lab_timestamps_always_oracle | analyst-partial | caught-by-interviewer | spec R050 (interviewer, data_confirmed=True) |
| belief_blank_rxnorm_inactive | analyst-belief | caught-by-interviewer | spec R004 (interviewer, data_confirmed=False) |
| belief_hold_means_stopped | analyst-belief | caught-by-dictionary | spec R095 (dictionary, data_confirmed=True) |
| belief_drugfile_all_correct | analyst-belief | caught-by-interviewer | spec R003 (interviewer, data_confirmed=False) |
| partial_src_vitals_metric | analyst-partial | caught-by-interviewer | spec R125 (interviewer, data_confirmed=True) |
| disagreement_duplicates | analyst-disagreement | caught-by-analyst | spec R144 (analyst, data_confirmed=False) |
| disagreement_sun_ridge_time | analyst-disagreement | caught-by-analyst | spec R146 (analyst, data_confirmed=True) |
| disagreement_void | analyst-disagreement | caught-by-analyst | spec R117 (analyst, data_confirmed=True) |

Summary: caught-by-analyst: 12, caught-by-dictionary: 4, caught-by-interviewer: 7, routed-to-runtime-question: 1

All 24 entries are carried correctly into the spec or routed to a runtime question. None was swallowed or
missed. Seven were caught only by the interviewer's own cross-checks, not by any single analyst or
document. Those are the partial truths: the guide and the analyst were each right for part of the data.

## The conversion

Bridge asked 73 questions:

| Question kind | Count | Answered by (simulated) | Answer |
|---|---|---|---|
| identity_match | 42 | Denise Okafor, HIM | same person (all 42: same address, compatible DOB/SSN4/name) |
| missing_birth_date (01/01/1900) | 6 | Denise | placeholder, flag for registration follow-up |
| nka_conflict | 8 | Denise | keep the allergy entries |
| retired_icd10 / icd9_one_to_many | 3 | Denise (HIM coding) | M54.50, F32.A, M17.9 from the descriptions |
| free_text_problem, missing_discharge, missing_subscriber_relationship, ambiguous_sex_code | 6 | Denise | keep text; in-progress + HIM list; age rule; sex at birth unknown |
| unmapped_lab SENDOUT | 1 | Ray Castillo | exclude (scanned send-out reports) |
| unmapped_medication MD0190, MD0199 | 2 | Priya Natarajan | exclude, list for pharmacist med rec |
| billing NPI, implausible vitals, `BMP` | 5 | nobody owns these | Bridge defaults: non-billing, drop, load as cancelled |

The run paused 4 times on its monitors (Condition hold rate; Allergy, Medication and Observation drop
rate; each explained below) and ended **completed**. End-of-run verification passed: counts, read-back
sampling, and all four clinical sentinels (17 active anticoagulants, 10 active insulin orders, 99 patients
with allergies, 526 abnormal labs, each matching).

| Resource | Loaded | Not loaded (why) | Mean fidelity |
|---|---|---|---|
| Patient | 301 | 42 merged duplicates | 0.978 |
| Coverage | 400 | | 0.997 |
| Encounter | 923 (incl. 11 left-without-being-seen, as cancelled) | 14 VOID entered in error | 0.998 |
| Condition | 381 | 15 duplicates after merge | 0.955 |
| AllergyIntolerance | 135 | 30 NKDA rows folded into the patient flag | 0.831 |
| MedicationRequest | 344 | 57 uncodable, listed for med rec | 0.965 |
| Observation | 4589 | 97 send-out, 54 cancelled, 36 implausible temps | 0.986 |
| Appointment | 467 | | 0.986 |

## Against ground truth
| Check | Checked | Correct | Wrong | Example of wrong |
|---|---|---|---|---|
| Cancelled lab results kept out of Nimbus | 54 | 54 | 0 |  |
| Coverage relationship = truth | 400 | 391 | 9 | 500025 self vs other; 500121 self vs spouse; 500210 self vs spouse |
| Encounter class = truth (incl. lowercase codes) | 923 | 923 | 0 |  |
| Encounter time zone (HVMC) | 623 | 623 | 0 |  |
| Encounter time zone (SRC) | 300 | 300 | 0 |  |
| Entered-in-error VOID visits kept out | 14 | 14 | 0 |  |
| HOLD orders loaded as on-hold | 69 | 69 | 0 |  |
| Lab collection time parsed (both formats) | 1125 | 1125 | 0 |  |
| Left-without-being-seen ED visits kept, as cancelled | 11 | 11 | 0 |  |
| Medication RxNorm = truth (incl. MD0108 drug-file error) | 344 | 344 | 0 |  |
| Patient sex = truth (X marker -> unknown) | 301 | 301 | 0 |  |
| Uncodable meds kept out for pharmacist med rec | 57 | 57 | 0 |  |
| Vital unit = truth (HVMC) | 1064 | 1064 | 0 |  |
| Vital unit = truth (SRC migrated pre-2016) | 129 | 129 | 0 |  |
| Vital unit = truth (SRC) | 268 | 268 | 0 |  |


- Identity pairwise precision 1.000, recall 0.977 (43/44 true duplicate pairs merged, 43 merges made)
- Planted issues surfaced: 1741/1741 (100.0%)

Value checks (testbed.scoring): 9325/9333 correct (99.9%)

| Check | Checked | Mismatched |
|---|---|---|
| Allergy substance code = answer key | 135 | 0 |
| AllergyIntolerance.recordedDate = ENTERED_DT | 135 | 0 |
| Appointment status = answer key | 448 | 0 |
| Appointment.start = APPT_DT | 467 | 0 |
| Condition ICD-10 code = answer key | 359 | 0 |
| Condition.abatementDate = RESOLVED_DT | 79 | 0 |
| Condition.onsetDate = ONSET_DT | 381 | 0 |
| Coverage.period.start = EFF_DT | 400 | 0 |
| Encounter.period.end = DISCH_DT | 754 | 0 |
| Encounter.period.start = ADMIT_DT | 923 | 0 |
| MedicationRequest.authoredOn = START_DT | 344 | 0 |
| Observation.effective = COLLECT_DT | 1125 | 0 |
| Observation.effective = TAKEN_DT | 3464 | 0 |
| Patient birthDate = answer key | 301 | 6 |
| Practitioner specialty = answer key | 18 | 2 |

## What went wrong, and what it means

1. **One duplicate pair was never proposed for review (identity recall 0.977; precision 1.000).** It is
   MARY/MARIE JOHNSON at both campuses with a blank SSN4: same DOB and same address, but it scores 0.58,
   under Bridge's 0.6 review threshold, because the matcher ignores the address. The same gap missed 4 pairs
   in the first, cleaner version of Meridian. **Proposed fix:** use the address as a matching signal. Not
   applied, because it changes which identity questions the Halcyon control run asks.
2. **9 coverage relationships are wrong.** All 9 are rows where `REL_CD` was blank in the source; the age
   rule called adult children and spouses "self". Unknowable from the data, and surfaced.
3. **6 birth dates are 01/01/1900 placeholders.** Loaded as flagged placeholders because the true DOB is
   unknowable.
4. **2 specialties are wrong** ("Gen Surg" → other). No analyst owns provider specialties; the gap is
   documented.
5. **Bugs found along the way, and fixed:**
   - The clinical sentinels used Halcyon's drug crosswalk instead of the run's own (first version).
   - The canonical binding presented derived units as source data (this version).
6. **Still Halcyon-worded:** the `BMP` question says "('B' = bumped by the clinic)", a meaning nobody at
   Meridian confirmed. Follow-up.

## What was built

- `testbed/meridian/`: generator, estate (guide, memo, 24-entry grading ledger), 4 analyst profiles,
  grader, demo.
- `src/bridge/interview/canonical.py`: delimited reader plus canonical binding. Field expressions include
  conditional `cases` (conventions that changed over time or by campus), chained lookups, multiple date
  formats, case folding, `exclude_unless`, and annotations for derived values.
- Profiler: delimited files; opt-in value distributions and format signatures.
- Spec generator: emits `format`/`canonical` into the reader binding and `SOURCE_NAME`/`CROSSWALKS` into
  the profile. Delphi and Halcyon specs are byte-identical to before.
- Terminology overlay per profile; `run --profile` (CLI) and `start_run(profile=)` (MCP); the run
  remembers its profile.
- `tools/interview.py`: shell driver for interviews.
- Tests: 823 pass, including ledger replay, re-profiling acceptance, canonical-expression units, and the
  graded end-to-end run.
