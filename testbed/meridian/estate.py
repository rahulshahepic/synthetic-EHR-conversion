"""Meridian's documentary estate: the vendor extract guide, the site kickoff memo, and the
grading ledger of every deliberate discrepancy between those documents (or the analysts'
beliefs) and the data. The guide and the memo ship in every export; the ledger goes to
``answer_key/estate_discrepancies.json`` only."""
from __future__ import annotations


def extract_guide() -> str:
    return """MERIDIAN CLINICAL SYSTEMS -- MCS/2 NIGHTLY EXTRACT GUIDE
DOCUMENT VERSION 3.2                                   REVISED 2014-08-11
APPLIES TO EXTRACT FORMAT 3.x

1. GENERAL
   Each extract file is a pipe-delimited (|) text file. The first row of every
   file is a header row naming the columns. Records end with CR/LF. Character
   set is ISO-8859-1 (Latin-1). There is no quoting or escaping; the pipe
   character is not permitted in data.
   Dates (columns ending _DT or _DATE) are MM/DD/YYYY.
   Timestamps (columns ending _TS) are YYYY-MM-DD HH:MM (24 hour).
   All timestamps are recorded in Mountain Time (MST/MDT) at the facility.
   Blank means unknown or not applicable.

2. FILES
   CAMPUS.DAT    Campuses (facilities)
   CLINIC.DAT    Clinics and nursing units; every clinic belongs to one campus
   STAFF.DAT     Providers and staff
   CARRIER.DAT   Insurance carriers
   INSPLAN.DAT   Insurance plans
   PERSON.DAT    Patient registration (one row per registration)
   INSCOV.DAT    Patient insurance coverage
   VISIT.DAT     Encounters
   PROBLEM.DAT   Problem list
   ALLERGY.DAT   Allergies
   DRUGFILE.DAT  Pharmacy drug file
   RXORDER.DAT   Medication orders
   TESTDICT.DAT  Laboratory test dictionary
   LABRES.DAT    Laboratory results
   VITALS.DAT    Vital signs (one row per measurement)
   IMMUNE.DAT    Immunization history
   APPT.DAT      Appointments

3. KEY COLUMNS
   CAMPUS_CD, CLINIC_CD, STAFF_ID, CARRIER_CD, PLAN_CD, PERSON_NO, COV_NO,
   VISIT_NO, PROB_NO, ALG_NO, DRUG_CD, RX_NO, TEST_CD, RES_NO, VS_NO, IMM_NO,
   APPT_NO identify a row of their file. PERSON_NO is the internal registration
   number and is the join key from all clinical files to PERSON.DAT.

4. COLUMN NOTES
   PERSON.MRN          Enterprise medical record number.
   PERSON.BIRTH_DT     Date of birth.
   PERSON.SEX_CD       1 = Male, 2 = Female, 9 = Unknown.
   PERSON.SSN_LAST4    Last four digits of SSN, may be blank.
   PERSON.RACE_TXT     Race as selected at registration.
   PERSON.NKA_YN       Y = patient has no known allergies.
   INSCOV.REL_CD       Subscriber relationship: S = Self, SP = Spouse,
                       D = Dependent, O = Other.
   INSCOV.PRIORITY     1 = primary, 2 = secondary.
   VISIT.VISIT_TYPE    OP = Outpatient, IP = Inpatient, ER = Emergency,
                       OBS = Observation, SDS = Same Day Surgery.
   VISIT.STATUS        OPEN, CLOSED, VOID (entered in error).
   PROBLEM.DX_CODE     Diagnosis code, stored with the decimal point
                       (e.g. E11.9, 250.00).
   PROBLEM.CODE_SYS    I9 = ICD-9-CM, I10 = ICD-10-CM.
   PROBLEM.STATUS      A = Active, I = Inactive, R = Resolved.
   ALLERGY.SEVERITY    SEVERE, MODERATE, MILD.
   DRUGFILE.RXNORM     RxNorm concept, maintained by Pharmacy.
   RXORDER.RX_STATUS   ACTIVE, DISCONTINUED, COMPLETED, HOLD (order on hold;
                       may be resumed).
   TESTDICT.LOINC      LOINC code for the test, maintained by the Laboratory.
   LABRES.COLLECTED_TS Specimen collection time (see section 1).
   LABRES.ABN          H = High, L = Low, A = Abnormal.
   LABRES.RESULT_STATUS F = Final, C = Corrected, P = Preliminary.
   VITALS.VS_TYPE      BP, HR, RR, TEMP, WT, HT, SPO2.
   VITALS.VS_UNIT      Unit of measure as sent by the flowsheet.
   APPT.APPT_STATUS    SCH = Scheduled, ARR = Arrived, CMP = Completed,
                       NOS = No show, CAN = Cancelled.
   APPT.LEN_MIN        Scheduled length in minutes.
"""


def kickoff_memo() -> str:
    return """HARBOR VALLEY HEALTH -- EHR CONVERSION KICKOFF MEMO

To:   Conversion team
From: Office of the CIO
Re:   Moving MCS/2 (Meridian) to Nimbus

Scope. Harbor Valley Health runs two campuses on Meridian MCS/2:
  - Harbor Valley Medical Center (HVMC), Las Cruces, New Mexico. Hospital,
    emergency department and clinics.
  - Sun Ridge Clinic (SRC), Tucson, Arizona. Family practice and urgent care.
    Sun Ridge was acquired in 2016 and moved onto MCS/2 that year; the
    enterprise MPI project ran at the same time.

The extract delivered to you is the nightly extract, format 4.0. The vendor's
extract guide is attached; it is the most recent one we have.

Your contacts for interviews:
  - Denise Okafor, Patient Access & HIM Manager (registration, problem lists)
  - Ray Castillo, Laboratory Information Systems Coordinator
  - Priya Natarajan, Pharmacy Informatics Pharmacist
  - Gary Lindqvist, Interface & Integration Analyst, IT (owns the extract)

Immunizations were never kept in MCS/2; the state registry is the record.
"""


# The grading ledger. Never shipped outside answer_key/; never read by Bridge.
DISCREPANCIES = [
    # --- the guide: mostly right, aged, with a few real errors
    {"id": "guide_version_skew", "kind": "dictionary",
     "claim": "guide 3.2 (2014) describes extract format 3.x", "truth": "the delivered extract is format 4.0 (manifest)",
     "how_to_check": "compare guide header with manifest.json extract_version"},
    {"id": "guide_timezone", "kind": "dictionary", "subject": "profile:facility_tz",
     "claim": "all timestamps are Mountain Time (MST/MDT)",
     "truth": "Sun Ridge (SRC, Tucson AZ) charts in America/Phoenix (no DST); HVMC is America/Denver",
     "how_to_check": "campus state; SRC summer timestamps are off by an hour if read as MDT"},
    {"id": "guide_dx_decimal_partial", "kind": "dictionary-partial", "subject": "field:PROBLEM.DAT.DX_CODE",
     "claim": "DX_CODE stored with the decimal point",
     "truth": "true for problems entered before the 2012 upgrade; since then the decimal point is stripped (E119)",
     "how_to_check": "DX_CODE format signatures: both 999.99 and 99999 shapes"},
    {"id": "guide_sex_codes_aged", "kind": "dictionary-aged", "subject": "field:PERSON.DAT.SEX_CD",
     "claim": "1 = Male, 2 = Female, 9 = Unknown", "truth": "right, plus 3 = X marker since 2021",
     "how_to_check": "distinct SEX_CD values"},
    {"id": "guide_rel_codes_partial", "kind": "dictionary-partial", "subject": "field:INSCOV.DAT.REL_CD",
     "claim": "S, SP, D, O",
     "truth": "S, P (spouse), C (child), O; D (dependent child) on Sun Ridge coverages from before 2016; SP never",
     "how_to_check": "distinct REL_CD values; D rows are SRC patients with EFF_DT before 2016-03"},
    {"id": "guide_visit_types_aged", "kind": "dictionary-aged", "subject": "field:VISIT.DAT.VISIT_TYPE",
     "claim": "OP, IP, ER, OBS, SDS", "truth": "also TH (telehealth, since 2020) -> virtual; about 1% keyed lowercase",
     "how_to_check": "distinct VISIT_TYPE values"},
    {"id": "guide_void_partial", "kind": "dictionary-partial", "subject": "field:VISIT.DAT.STATUS",
     "claim": "VOID = entered in error",
     "truth": "true, except that since 2018 ED visits where the patient left without being seen are also VOID; those are real (cancelled) visits with triage vitals",
     "how_to_check": "VOID ER visits after 2018 with VITALS rows"},
    {"id": "guide_lab_timestamp_partial", "kind": "dictionary-partial", "subject": "field:LABRES.DAT.COLLECTED_TS",
     "claim": "YYYY-MM-DD HH:MM",
     "truth": "DD-MON-YY HH:MM, except Sun Ridge rows since the 2024 analyzer interface, which are YYYY-MM-DD HH:MM",
     "how_to_check": "COLLECTED_TS format signatures"},
    {"id": "guide_result_status_aged", "kind": "dictionary-aged", "subject": "field:LABRES.DAT.RESULT_STATUS",
     "claim": "F, C, P", "truth": "F, C, and X = cancelled (must not convert); P never occurs",
     "how_to_check": "distinct RESULT_STATUS values"},
    {"id": "guide_appt_status_aged", "kind": "dictionary-aged", "subject": "field:APPT.DAT.APPT_STATUS",
     "claim": "SCH, ARR, CMP, NOS, CAN", "truth": "also BMP (bumped by clinic), which has no Nimbus status",
     "how_to_check": "distinct APPT_STATUS values"},
    {"id": "guide_stale_immune", "kind": "dictionary", "subject": "file:IMMUNE",
     "claim": "IMMUNE.DAT is part of the extract", "truth": "no such file; immunizations were never in MCS/2",
     "how_to_check": "file list"},
    {"id": "guide_hold_right", "kind": "dictionary-right", "subject": "field:RXORDER.DAT.RX_STATUS",
     "claim": "HOLD = order on hold, may be resumed", "truth": "right (HOLD orders carry no stop date); the pharmacist's belief is wrong",
     "how_to_check": "RX_STATUS x STOP_DT blank"},
    {"id": "undocumented_placeholder_dob", "kind": "dictionary", "subject": "field:PERSON.DAT.BIRTH_DT",
     "claim": "BIRTH_DT is the date of birth", "truth": "01/01/1900 is the registration placeholder for an unknown DOB",
     "how_to_check": "BIRTH_DT value 01/01/1900 pile"},
    {"id": "drugfile_wrong_rxnorm", "kind": "reference-data", "subject": "codeset:formulary",
     "claim": "DRUGFILE MD0108 (levothyroxine 50 mcg) RXNORM 966221", "truth": "966222; nobody at the site knows",
     "how_to_check": "cross-check drug descriptions against an RxNorm reference"},
    # --- analysts: right, partly right, wrong
    {"id": "belief_mpi_no_duplicates", "kind": "analyst-belief", "analyst": "registration",
     "claim": "the 2016 MPI project merged every duplicate; PERSON_NO is one row per person",
     "truth": "pre-2016 cross-campus duplicates were never merged; same-campus duplicates also exist",
     "how_to_check": "answer_key/persons.json"},
    {"id": "belief_cancelled_results_purged", "kind": "analyst-belief", "analyst": "lab",
     "claim": "cancelled results are purged before the extract", "truth": "RESULT_STATUS X rows are present",
     "how_to_check": "RESULT_STATUS distinct values include X"},
    {"id": "partial_lab_timestamps_always_oracle", "kind": "analyst-partial", "analyst": "lab",
     "claim": "COLLECTED_TS is always DD-MON-YY", "truth": "except Sun Ridge since 2024 (YYYY-MM-DD HH:MM)",
     "how_to_check": "COLLECTED_TS format signatures"},
    {"id": "belief_blank_rxnorm_inactive", "kind": "analyst-belief", "analyst": "pharmacy",
     "claim": "drug file rows without RxNorm are only on old inactive orders, safe to skip",
     "truth": "MD0190/MD0199 sit on active and held orders",
     "how_to_check": "RXORDER DRUG_CD x RX_STATUS"},
    {"id": "belief_hold_means_stopped", "kind": "analyst-belief", "analyst": "pharmacy",
     "claim": "HOLD means the prescriber stopped it; treat as discontinued", "truth": "on-hold (guide is right)",
     "how_to_check": "HOLD orders have no STOP_DT"},
    {"id": "belief_drugfile_all_correct", "kind": "analyst-belief", "analyst": "pharmacy",
     "claim": "every RxNorm in the drug file is right", "truth": "MD0108 is wrong (966221 vs 966222)",
     "how_to_check": "reference cross-check"},
    {"id": "partial_src_vitals_metric", "kind": "analyst-partial", "analyst": "interface",
     "claim": "Sun Ridge vitals are metric with the unit filled in",
     "truth": "since the 2016 move; migrated Sun Ridge history before 2016-03 is US units with a blank unit",
     "how_to_check": "SRC VITALS rows with blank VS_UNIT, by date"},
    {"id": "disagreement_duplicates", "kind": "analyst-disagreement", "analysts": ["registration", "interface"],
     "claim": "registration: no duplicates remain; interface: cross-campus duplicates from before 2016 remain",
     "truth": "interface is right; every merge is still a human decision", "how_to_check": "answer_key/persons.json"},
    {"id": "disagreement_sun_ridge_time", "kind": "analyst-disagreement", "analysts": ["registration", "interface"],
     "claim": "registration: everything is Mountain Time; interface: Sun Ridge is Arizona time",
     "truth": "interface is right (America/Phoenix)", "how_to_check": "campus state"},
    {"id": "disagreement_void", "kind": "analyst-disagreement", "analysts": ["registration", "interface"],
     "claim": "registration: ED VOIDs since 2018 include left-without-being-seen visits; interface: VOID is entered in error",
     "truth": "registration is right for ED VOIDs since 2018 (they have triage vitals); other VOIDs are errors",
     "how_to_check": "answer_key truth void_kind"},
]
