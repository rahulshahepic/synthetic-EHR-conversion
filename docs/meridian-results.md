# Meridian: Socratic interview and end-to-end conversion results

A third synthetic source system ([Meridian](meridian.md)) was built, interviewed with the Socratic import
builder, converted into Nimbus through the spec that interview generated, and graded against its answer
key. Reproduce everything with `python -m testbed.meridian.demo --out demo_meridian` (about 3 seconds).

## Read this first: what this does and does not prove

- **The interview was not blind.** The same agent (Claude) built Meridian, wrote the analyst profiles, ran
  the interview and role-played the analysts. The firewall held mechanically (estate documents only through
  `read_estate`; the answer key and profiles were refused when tried), but the interviewer knew the planted
  problems from writing them. The scorecard below measures whether the *pipeline* (profiler, claims,
  disputes, spec generator, canonical staging, runtime questions) carries each fact through correctly. It
  does not measure how good an interviewer is at finding what it doesn't already know. A blind run needs a
  separate analyst backend (the live-LLM backend `build_profile_prompt` is designed for).
- **Runtime answers are attributed to simulated analysts** (`sim-analyst:<name>`), never to a real user.
  Each answer follows what that analyst said in the interview and what the question shows. None was taken
  from the answer key. Questions outside every analyst's area kept Bridge's defaults.
- **Go-live readiness is NO-GO on purpose.** It needs named humans to acknowledge the pause alerts and sign
  off on fidelity loss. That was left for a human.

## The interview (ledger `src/bridge/interview/ledgers/meridian.jsonl`, 389 events)

1. **Estate documents.** Read the kickoff memo, the manifest and the vendor guide. The guide is v3.2 for
   format 3.x, but the manifest says 4.0, so the guide was recorded as stale from the start.
2. **Profiling.** 16 files, 117 field observations (with value distributions for code-like fields). The
   profiler alone contradicted the guide on 9 fields: `SEX_CD` has 3 and 9; `REL_CD` has P and C;
   `VISIT_TYPE` has TH; no `DX_CODE` has a decimal; `COLLECTED_TS` is `DD-MON-YY`; `RESULT_STATUS` has C and
   X; `VS_UNIT` is 88% blank; `APPT_STATUS` has BMP; `BIRTH_DT` piles on 01/01/1900. Each became a dispute.
3. **Interviews.** 33 questions to the 4 analysts, aimed at the open disputes and the checklist.
4. **Testing beliefs against data.** Ray said cancelled results are purged, but the profiler shows 69 `X`
   rows. Confronted with that, Ray said they're cancelled and must not convert. Priya said RxNorm-less drugs
   are only on old orders, but a cross-tab shows 23 active and 17 on-hold orders. Denise said the MPI
   removed all duplicates, but 23 DOB+SSN4 groups span both campuses, which supports Gary's account.
   Denise and the guide said "everything is Mountain Time", but `CAMPUS.STATE` puts Sun Ridge in Arizona,
   which supports Gary's America/Phoenix.
5. **Resolutions.** 12 disputes were resolved, each citing its evidence. One was left open deliberately:
   nobody knew what `BMP` means, so it routes to a runtime question.
6. **Coverage checklist.** 139 items covered, 1 disputed, 0 open.
7. **Spec.** 165 rules (117 data-confirmed), 2 known unknowns, and the identity merge-policy override.

## Interview scorecard
| Entry | Kind | Verdict | How |
|---|---|---|---|
| guide_version_skew | dictionary | caught-by-dictionary | spec R009 (dictionary, data_confirmed=False) |
| guide_timezone | dictionary | caught-by-analyst | spec R145 (analyst, data_confirmed=True) |
| guide_dx_decimal | dictionary | caught-by-analyst | spec R079 (analyst, data_confirmed=True) |
| guide_sex_codes | dictionary | caught-by-analyst | spec R073 (analyst, data_confirmed=True) |
| guide_rel_codes | dictionary | caught-by-analyst | spec R042 (analyst, data_confirmed=True) |
| guide_visit_types | dictionary | caught-by-analyst | spec R118 (analyst, data_confirmed=True) |
| guide_lab_timestamp | dictionary | caught-by-analyst | spec R049 (analyst, data_confirmed=True) |
| guide_result_status | dictionary | caught-by-analyst | spec R053 (analyst, data_confirmed=True) |
| guide_vs_unit | dictionary | caught-by-analyst | spec R124 (analyst, data_confirmed=True) |
| guide_appt_status | dictionary | routed-to-runtime-question | known unknown in the spec |
| guide_stale_immune | dictionary | caught-by-dictionary | spec R132 (dictionary, data_confirmed=False) |
| undocumented_placeholder_dob | dictionary | caught-by-analyst | spec R060 (analyst, data_confirmed=True) |
| belief_mpi_no_duplicates | analyst-belief | caught-by-analyst | spec R143 (analyst, data_confirmed=False) |
| belief_cancelled_results_purged | analyst-belief | caught-by-analyst | spec R053 (analyst, data_confirmed=True) |
| belief_blank_rxnorm_inactive | analyst-belief | caught-by-interviewer | spec R003 (interviewer, data_confirmed=False) |
| disagreement_duplicates | analyst-disagreement | caught-by-analyst | spec R143 (analyst, data_confirmed=False) |
| disagreement_sun_ridge_time | analyst-disagreement | caught-by-analyst | spec R145 (analyst, data_confirmed=True) |

Summary: caught-by-analyst: 13, caught-by-dictionary: 2, caught-by-interviewer: 1, routed-to-runtime-question: 1

All 17 grading entries were carried into the spec correctly or routed to a runtime question. None was
swallowed or missed (see the caveat above about what this measures).

## The conversion

The run paused 5 times (monitors: Patient and Condition hold rate, Allergy, Medication and Observation drop
rate) and asked 79 questions in total:

| Question kind | Count | Answered by (simulated) | Answer |
|---|---|---|---|
| identity_match | 52 | Denise Okafor, HIM | same person (all 52: same address, compatible DOB/SSN4/name) |
| missing_birth_date (01/01/1900) | 3 | Denise | placeholder, flag for registration follow-up |
| ambiguous_sex_code (X marker) | 1 | Denise | sex at birth unknown, gender identity unset |
| nka_conflict | 7 | Denise | keep the allergy entries |
| retired_icd10 / icd9_one_to_many | 3 | Denise (HIM coding) | M54.50, F32.A, M17.9 from the descriptions |
| free_text_problem | 3 | Denise | keep as uncoded text |
| missing_discharge, missing_subscriber_relationship | 2 | Denise | in-progress + HIM list; age rule |
| unmapped_lab SENDOUT | 1 | Ray Castillo, lab | exclude (scanned send-out reports) |
| unmapped_medication MD0190, MD0199 | 2 | Priya Natarajan, pharmacy | exclude, list for pharmacist med rec |
| billing_provider_without_npi, implausible_vital, BMP status | 5 | nobody owns these | Bridge defaults: non-billing, drop, load as cancelled |

Final state: **completed**. End-of-run verification passed: counts, read-back sampling, and all four
clinical sentinels (17 active anticoagulants, 10 active insulin orders, 95 patients with allergies, 580
abnormal labs, each matching).

| Resource | Loaded | Not loaded (why) | Mean fidelity |
|---|---|---|---|
| Patient | 304 | 52 merged duplicates | 0.978 |
| Coverage | 402 | | 0.997 |
| Encounter | 1007 | 20 VOID (entered in error) | 1.000 |
| Condition | 406 | 18 duplicates after merge | 0.954 |
| AllergyIntolerance | 123 | 26 NKDA rows folded into the patient flag | 0.853 |
| MedicationRequest | 355 | 60 uncodable, listed for med rec | 0.957 |
| Observation | 5107 | 102 send-out, 69 cancelled, 26 implausible temps | 0.987 |
| Appointment | 433 | | 0.980 |

## Against ground truth
| Check | Checked | Correct | Wrong | Example of wrong |
|---|---|---|---|---|
| Cancelled lab results kept out of Nimbus | 69 | 69 | 0 |  |
| Coverage relationship = truth | 402 | 389 | 13 | 500001 self vs spouse; 500035 self vs child; 500065 self vs child |
| Encounter class = truth | 1007 | 1007 | 0 |  |
| Encounter time zone (HVMC) | 675 | 675 | 0 |  |
| Encounter time zone (SRC) | 332 | 332 | 0 |  |
| Lab collection time parsed (DD-MON-YY) | 1181 | 1181 | 0 |  |
| Medication RxNorm = truth | 355 | 355 | 0 |  |
| Patient sex = truth (X marker -> unknown) | 304 | 304 | 0 |  |
| Uncodable meds kept out for pharmacist med rec | 60 | 60 | 0 |  |
| Vital unit = campus convention (HVMC) | 1201 | 1201 | 0 |  |
| Vital unit = campus convention (SRC) | 470 | 470 | 0 |  |


- Identity pairwise precision 1.000, recall 0.931 (54/58 true duplicate pairs merged, 54 merges made)
- Planted issues surfaced: 1745/1745 (100.0%)

Value checks (testbed.scoring): 9968/9974 correct (99.9%)

| Check | Checked | Mismatched |
|---|---|---|
| Allergy substance code = answer key | 123 | 0 |
| AllergyIntolerance.recordedDate = ENTERED_DT | 123 | 0 |
| Appointment status = answer key | 407 | 0 |
| Appointment.start = APPT_DT | 433 | 0 |
| Condition ICD-10 code = answer key | 383 | 0 |
| Condition.abatementDate = RESOLVED_DT | 77 | 0 |
| Condition.onsetDate = ONSET_DT | 406 | 0 |
| Coverage.period.start = EFF_DT | 402 | 0 |
| Encounter.period.end = DISCH_DT | 829 | 0 |
| Encounter.period.start = ADMIT_DT | 1007 | 0 |
| MedicationRequest.authoredOn = START_DT | 355 | 0 |
| Observation.effective = COLLECT_DT | 1181 | 0 |
| Observation.effective = TAKEN_DT | 3926 | 0 |
| Patient birthDate = answer key | 304 | 4 |
| Practitioner specialty = answer key | 18 | 2 |


## What went wrong, and what it means

1. **4 duplicate pairs were never proposed for review (identity recall 0.931; precision 1.000).** All are
   cross-campus pairs with a blank SSN4 plus the nickname ELENA/LENA (missing from Bridge's nickname list)
   or a day/month-swapped DOB. They score below Bridge's 0.6 review threshold, even though the address
   matches exactly. **Proposed fix:** use the address as a matching signal and extend the nickname list.
   Not applied here, because it changes which identity questions the Halcyon control run asks.
2. **13 coverage relationships are wrong.** All are rows where `REL_CD` was blank in the source. Bridge
   asked, the age rule was accepted, and adult children and spouses came out as "self". Unknowable from
   the data, and surfaced.
3. **4 birth dates are wrong.** Three are the 01/01/1900 placeholders, loaded as flagged placeholders
   because the true DOB is unknowable. The fourth is the unmerged duplicate from item 1.
4. **2 specialties are wrong** ("Gen Surg" → other). No interviewed analyst owns provider specialties, so
   the interview documented the gap instead of guessing.
5. **Bug found during the run and fixed.** The clinical sentinels resolved drug codes through the
   hand-written Halcyon crosswalk instead of the run's own profile. Verification correctly refused to pass
   (17 "unexplained" anticoagulants), which is how it was found. `verify.py` now uses the run's profile
   terminology.
6. **Misleading prompt wording.** Mapper prompts are written for Halcyon: the `BMP` question says
   "('B' = bumped by the clinic)", a meaning nobody at Meridian confirmed. The source name is substituted;
   the rest of the text is not. Follow-up: make source-specific prompt text come from the profile.

## What was built

- `testbed/meridian/`: generator, estate (guide, memo, grading ledger), 4 analyst profiles, grader, demo.
- `src/bridge/interview/canonical.py`: delimited reader + canonical binding (spec-driven staging into the
  mappers' shape); `delimited` reader in the registry.
- Spec generator: emits `format` and `canonical` into the reader binding, plus `SOURCE_NAME` and
  `CROSSWALKS` in the profile. Delphi and Halcyon specs are unchanged byte-for-byte.
- Profiler: delimited files, and opt-in value distributions (off by default, so recorded observations are
  stable).
- Terminology: `OverlayTerminology` / `terms_for(profile)` layer a profile's crosswalks over Bridge's.
- Runner/CLI/MCP: `run --profile <name>` (MCP `start_run(..., profile=)`); the run remembers its profile,
  so resume, reprocess and verify map with the same one. Spec-excluded rows drop visibly with a loss-ledger reason.
- `tools/interview.py`: shell driver for an interview (profile, ask, claim, resolve, checklist, generate).
- Tests: `tests/bridge/test_interview_meridian.py`, `tests/testbed/test_meridian.py` (41 tests, including
  ledger replay, re-profiling acceptance, and the graded end-to-end run). Full suite: 820 passed.
