# Source EHR: Meridian (invented, test-only)

Meridian MCS/2 is a fictional legacy EHR run by a fictional two-campus system, **Harbor Valley Health**:
Harbor Valley Medical Center (HVMC, Las Cruces NM) and Sun Ridge Clinic (SRC, Tucson AZ, acquired 2016).
It lives in `testbed/meridian/` and is the third source shape alongside Halcyon (SQLite + HL7 + CSV) and
Delphi (fixed-width). It is the first source converted **end-to-end** through an import spec the
Socratic builder generated, with no hand-written Bridge code specific to it.

```
python -m testbed.meridian generate --out exports/meridian --seed 42 --patients 300
python -m bridge --run-db runs/meridian.db run --source exports/meridian --profile meridian
python -m testbed.meridian.demo --out demo_meridian        # whole thing, analysts role-played, graded
```
MCP: `start_run(source="exports/meridian", profile="meridian")`.

## Export

Sixteen pipe-delimited files with a header row (`CAMPUS`, `CLINIC`, `STAFF`, `CARRIER`, `INSPLAN`, `PERSON`,
`INSCOV`, `VISIT`, `PROBLEM`, `ALLERGY`, `DRUGFILE`, `RXORDER`, `TESTDICT`, `LABRES`, `VITALS`, `APPT`, all
`.DAT`, Latin-1, CRLF), `manifest.json`, and the estate documents: the vendor's `MCS2_EXTRACT_GUIDE.TXT`
(version 3.2, 2014, for extract format 3.x; the extract is 4.0) and the CIO's `KICKOFF_MEMO.TXT`.
`answer_key/` holds ground truth in the Halcyon shapes (`persons.json`, `truth.json`, `issues.jsonl`) plus
the estate grading ledger `estate_discrepancies.json`. Bridge never reads it.

## What is hard about it

| Problem | Where it shows |
|---|---|
| Guide says all times are Mountain Time; Sun Ridge is Arizona (no DST) | every SRC timestamp, half the year |
| ICD codes stored without the decimal point; ICD-9 before Oct 2015 | `PROBLEM.DX_CODE`, `CODE_SYS` |
| Sex codes 1/2/9 and 3 (X marker); guide says 0/1/2 | `PERSON.SEX_CD` |
| `01/01/1900` is the desk's unknown-DOB placeholder | `PERSON.BIRTH_DT` |
| Relationship codes S/P/C/O; guide says S/SP/D/O | `INSCOV.REL_CD` |
| Telehealth visit type `TH`, undocumented | `VISIT.VISIT_TYPE` |
| Lab timestamps Oracle-style `DD-MON-YY HH:MM` | `LABRES.COLLECTED_TS` |
| Cancelled results (`X`) present though "purged" | `LABRES.RESULT_STATUS` |
| HVMC vitals have no unit (US units implied); SRC sends metric | `VITALS.VS_UNIT` |
| Appointment status `BMP`, undocumented, nobody knows it | `APPT.APPT_STATUS` |
| Pre-2016 cross-campus duplicate registrations never merged | `PERSON` |
| Drug file rows without RxNorm on active orders | `DRUGFILE.RXNORM`, `RXORDER` |
| Guide lists `IMMUNE.DAT`; it never existed | file list |

## Analysts

Four first-person profiles in `testbed/meridian/analysts/` (private to the analyst simulator; the
interviewer reaches them only through `ask`): Denise Okafor (patient access & HIM), Ray Castillo (lab
systems), Priya Natarajan (pharmacy informatics), Gary Lindqvist (interface & integration, owns the
extract). They carry three wrong beliefs (no duplicates remain; cancelled results are purged; RxNorm-less
drugs are only on inactive orders) and disagree on duplicates and on Sun Ridge's time zone.

## How Bridge reads it

The interview produced `src/bridge/interview/specs/meridian/` (ledger: `ledgers/meridian.jsonl`). Its
reader binding names the generic `delimited` reader and carries a **canonical binding**: for each Nimbus
resource type, which file and which source field plays each role the mappers read, with value
conventions (date formats, code maps, placeholders, decimal re-insertion, rows to exclude). See
`src/bridge/interview/canonical.py`. The profile's `CROSSWALKS` overlay Bridge's terminology for the
source's own code sets. Results: [Meridian results](meridian-results.md).
