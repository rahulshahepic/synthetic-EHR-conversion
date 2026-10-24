# Source EHR: Halcyon Classic (invented, test-only)

Halcyon is a fictional late-90s client/server EHR used by a fictional 3-facility health system ("Riverbend Health"). It lives entirely in `testbed/halcyon/` and exists only to give Bridge something realistic and messy to convert. **Bridge must treat it as a black box export**, exactly as a real conversion team would.

## Export layout
`python -m testbed.halcyon generate --out <dir> --seed 42 --patients 500` writes:

```
<dir>/
  halcyon.db                 # SQLite snapshot of the operational DB
  feeds/adt_*.hl7            # HL7 v2.3 ADT (A04 register, A08 update, A40 merge)
  feeds/oru_*.hl7            # HL7 v2.3 ORU^R01 lab results (some labs exist ONLY here)
  feeds/siu_*.hl7            # HL7 v2.3 SIU^S12/S15 scheduling
  extracts/immunizations.csv # state-registry style extract (pipe-delimited, latin-1)
  extracts/charge_master.csv # charge description master
  manifest.json              # seed, counts, generator version (NOT answer key)
  answer_key/                # ground truth for tests ONLY; Bridge must never read it
```

## DB tables (abridged; full DDL in `testbed/halcyon/schema.sql`)
| Table | Notes / planted messiness |
|---|---|
| `FACILITY`, `DEPT` | Two-level hierarchy only (Nimbus needs three: org → site → department). Some depts shared across facilities. |
| `PROVIDER` | `NAME` as `"LAST, FIRST M MD"`; `NPI` missing for ~8%; specialty free text ("Fam Med", "FAMILY PRACTICE", "FP"). Inactive providers still referenced by old encounters. |
| `PAT` | Per-facility MRN (`MRN`, `FAC_ID`) — one person may have several. `PAT_NAME` single field `"LAST,FIRST MIDDLE"`; `DOB` `YYYYMMDD` text (some `00000000`, some 2-digit years); `SEX` in `M/F/U/X/O/blank`; `RACE` free text; address lines concatenated with `^`; phones in 6 formats. ~4% duplicate persons with typos. |
| `PAT_ALIAS` | Previous names, AKA. |
| `VISIT` | Visit type local codes (`OV`, `OVN`, `ER`, `IP`, `TEL`, `OBS`, `XX`); discharge datetime missing for some inpatient; times in local time without zone, across a DST change. |
| `DX` | Problem list mixing ICD-9 (pre-2015), ICD-10, local `Z`-codes, and free text only. Status `A/I/R/blank`. |
| `MED_ORD` | Local formulary code (`HFORM####`) + free-text drug name + free-text sig (`"1 tab po bid x10d prn pain"`). Dose stored as `"500MG"`, `"0.5 mg"`, `"1/2 tab"`. |
| `ALLERGY` | Free-text allergen (`"PCN"`, `"penicillin"`, `"sulfa"`), reactions concatenated `"HIVES;SOB"`, severity `MILD/MOD/SEV/blank`. `NKA` rows that conflict with real allergies. |
| `LAB_RESULT` | Local test codes (`GLU`, `K`, `HGBA1C`); values as text incl. `"<5"`, `">1000"`, `"POS"`, `"see note"`; units non-UCUM (`"mg/dl"`, `"MEQ/L"`); ref range as `"3.5-5.1"`. |
| `VITALS` | Wide table; BP as `"120/80"`; temp in °F or °C with no unit column; weight lb vs kg inferred by facility. |
| `NOTE` | RTF-ish blob with Halcyon formatting codes; some > 64 KB truncated in the DB but complete in no other channel (unrecoverable loss). |
| `IMMUN` | CVX for some rows, local codes for others; registry CSV overlaps but disagrees on dates. |
| `SCHED` | Appointments; status `S/C/N/A/B/X` (`B` = bumped, no Nimbus equivalent). Recurring templates. |
| `PAYER`, `PLAN`, `COVERAGE` | Subscriber relationship codes `01/18/19/G8/blank`; COB order sometimes duplicated. |
| `CHARGE` | CPT or local charge code (map via charge master); modifiers concatenated `"25 59"`; units; amounts in cents vs dollars depending on era. |
| `USERS` | Logins incl. shared/generic accounts (`FRONTDESK1`). |

## Channel overlap rules (ground truth used by generator)
- ADT A08 updates are **newer** than `PAT` for demographics they contain.
- ADT A40 merges indicate the surviving MRN; the DB may not reflect the merge yet.
- ORU results for the last 30 days exist only in feeds; older ones exist in both (dedupe on accession + test code).
- SIU and `SCHED` overlap; SIU wins on status if newer.

## Planted problems (with injection rates configurable in `testbed/halcyon/config.py`)
Duplicate persons, invalid/missing dates, unmappable codes, ICD-9 one-to-many crosswalks, ambiguous units, conflicting allergy lists, orphan references (encounter with deleted provider), truncated notes, encoding issues (latin-1 names: `José`, `Zoë`), timezone/DST ambiguity, retired codes, out-of-range vitals (typos like weight 1800 lb).

The `answer_key/` lists every planted issue so tests can measure Bridge's detection recall. **Bridge code must never read `answer_key/`.**
