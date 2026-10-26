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

Meridian is meant to be messy the way real estates are. The vendor guide is **mostly right**. Where it is
wrong, that is usually because it is old, and on several points it is right for older data and wrong for
newer data. The analysts know the reality for their own corner, but they are sometimes partly right or
plainly wrong, and they disagree with each other. Conventions changed over time and differ by campus.

| Topic | Guide says | Analysts say | Data shows |
|---|---|---|---|
| Time zone | all Mountain Time | Denise: one clock, Mountain. Gary: Sun Ridge is Arizona, no DST | SRC is in AZ (Gary is right) |
| Problem codes | stored with the decimal | Denise: stripped since the 2012 upgrade | dotted before 2012, dotless after (both right) |
| Relationship codes | S, SP, D, O | Denise: S, P, C, O; "D isn't ours" | D only on migrated pre-2016 Sun Ridge coverages (guide right for those) |
| Lab timestamps | YYYY-MM-DD HH:MM | Ray: always DD-MON-YY | DD-MON-YY, except Sun Ridge since 2024 in the guide's format |
| Cancelled labs | F, C, P | Ray: cancelled results are purged | 54 `X` rows present |
| Vital units | "as sent by the flowsheet" | Gary: HVMC blank = US, SRC metric with unit; hazy on the migration | SRC history before March 2016 is blank-unit US (Gary partly right) |
| VOID visits | entered in error | Gary: entered in error. Denise: ED VOIDs since 2018 include left-without-being-seen | ER VOIDs with triage vitals are real visits (Denise is right) |
| HOLD orders | on hold, may resume | Priya: treat as discontinued | HOLD orders have no stop date (guide is right) |
| Drug file RxNorm | maintained by Pharmacy | Priya: all hand-checked, all right | MD0108 is wrong (966221; levothyroxine 50 mcg is 966222) |
| RxNorm-less drugs | (not covered) | Priya: only on old inactive orders, skip | 26 active, 11 held orders |
| Duplicates | (not covered) | Denise: MPI merged all. Gary: pre-2016 cross-campus ones remain | Gary is right |
| Sex codes | 1, 2, 9 | Denise: plus 3 = X marker since 2021 | 1, 2, 3, 9 |
| Visit types | OP, IP, ER, OBS, SDS | Gary: plus TH; lowercase is just typing | TH, plus 11 lowercase codes |
| Appointment `BMP` | (absent) | nobody knows | 19 rows |
| `IMMUNE.DAT` | listed | Gary: never existed | absent |
| DOB 01/01/1900 | (absent) | Denise: desk placeholder | 6 rows |

## Analysts

Four first-person profiles in `testbed/meridian/analysts/` (private to the analyst simulator; the
interviewer reaches them only through `ask`): Denise Okafor (patient access & HIM), Ray Castillo (lab
systems), Priya Natarajan (pharmacy informatics), Gary Lindqvist (interface & integration, owns the
extract). Between them they hold four wrong beliefs and two partial truths, and they disagree on three
points (duplicates, Sun Ridge's clock, VOID). The grading ledger (`answer_key/estate_discrepancies.json`,
24 entries) labels each entry: dictionary, dictionary-partial, dictionary-aged, dictionary-right,
reference-data, analyst-belief, analyst-partial, or analyst-disagreement.

## How Bridge reads it

The interview produced `src/bridge/interview/specs/meridian/` (ledger: `ledgers/meridian.jsonl`). Its
reader binding names the generic `delimited` reader and carries a **canonical binding**: for each Nimbus
resource type, which file and which source field plays each role the mappers read, with value
conventions (date formats, code maps, placeholders, decimal re-insertion, conditional rules for conventions that changed over time, rows to exclude and their exceptions). A value the spec derives rather than reads is annotated as inferred in the record's fidelity. See
`src/bridge/interview/canonical.py`. The profile's `CROSSWALKS` overlay Bridge's terminology for the
source's own code sets. Results: [Meridian results](meridian-results.md).
