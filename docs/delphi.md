# Source EHR: Delphi (invented, test-only)

Delphi is a fictional legacy EHR from Delphi Health Systems, used by a single fictional hospital ("St. Ambrose Memorial"). It lives entirely in `testbed/delphi/` and exists to give this project a second, differently-shaped legacy system alongside Halcyon.

Where Halcyon's data problems come from feeds and relational drift, Delphi's come from the medium itself: everything is a fixed-width text file, every department keeps its own patient numbering, and most clinical content is typed prose. The name is the vendor's.

Delphi is an **estate**, not just an export. Alongside the data, the testbed ships the documents a conversion team would actually be handed — a vendor data dictionary of uncertain reliability, and the recorded knowledge of the staff who work the system (see "The estate" below). Bridge does not read Delphi yet. Onboarding it is a separate task, planned as an interview-driven process that works from the estate; nothing about Delphi's formats should be hand-coded into Bridge in advance.

## Export layout
`python -m testbed.delphi generate --out <dir> --seed 42 --patients 500` writes:

```
<dir>/
  REG.TXT        # registration accounts (one record per account; coverage + allergies live here)
  ENC.TXT        # encounters
  DX.TXT         # problem list (shorthand code + typed text)
  LAB.TXT        # laboratory accounts + results (Julian dates)
  LABDICT.TXT    # lab test dictionary (description, unit, reference range)
  RAD.TXT        # radiology accounts + exams (report text on the exam record)
  PHA.TXT        # pharmacy accounts + medication orders (by NDC)
  NOTE.TXT       # note headers + 72-column continuation records
  BILL.TXT       # charges (amounts in cents)
  CHGDICT.TXT    # charge dictionary (charge code -> description, CPT where assigned)
  DXDICT.TXT     # diagnosis shorthand dictionary
  APPT.TXT       # appointments
  PROV.TXT       # providers
  JOURNAL.TXT    # the transaction journal: add / change / delete entries for everything above
  LAYOUTS.DAT    # machine-readable record layouts, version 5.0 (the format contract)
  DATADICT.TXT   # the vendor's data dictionary, version 4.1 (see "The estate")
  manifest.json  # seed, counts, generator version (NOT answer key)
  answer_key/    # ground truth for tests ONLY; no conversion process may read it
```

Every extract file has one fixed record length — the widest of its record types — and every record starts with a 2-character record type. `LAYOUTS.DAT` defines each record type's fields by starting position and length, in the form `FILE|RT|FIELD|START|LEN|TYPE|DESC`. There are no delimiters in the data files and no header rows. Text is uppercase and encoded latin-1.

## How Delphi differs from Halcyon

| Axis | Halcyon | Delphi |
|---|---|---|
| Export paradigm | SQLite snapshot + HL7 v2 feeds + CSV extracts | Flat fixed-width text files only; no database, no HL7 |
| Change feed | ADT A08/A40 messages | `JOURNAL.TXT`, a fixed-width transaction journal (A/C/D entries) |
| Patient identity | Per-facility MRN, one PAT table, alias table | No master patient index; registration, lab, radiology and pharmacy each assign their own account numbers |
| Dates | `YYYYMMDD` text, some 2-digit years | `YYMMDD` with a pivot year of 30; lab dates are Julian (2-digit year + day of year); times are minutes since midnight |
| Diagnoses | ICD-9 / ICD-10 / local codes on a problem table | Typed free text, optionally with a local shorthand code (`DM2`, `HTN`, ...) expanded in `DXDICT.TXT` |
| Medications | Local formulary code + free-text drug name and sig | 11-digit NDC + free-text dose and sig |
| Lab results | Discrete value/unit/ref-range columns | One result string with the flag appended (`12.4H`); units and reference ranges live in `LABDICT.TXT` |
| Allergies | Allergy table with reaction/severity columns | A 40-character free-text field on the registration account |
| Charges | Charge table + CSV charge master, dollars or cents by era | Charge file + `CHGDICT.TXT`; amounts always integer cents |
| Generator | Direct per-table synthesis | Event-sourced: a chronological journal of departmental events is simulated first, then the extracts are materialized from it |

## Conventions in the data

- **Accounts, not patients.** A person typically holds 2–4 accounts (registration, plus one per department that has served them). The same person appears under each account with the name and birth date as that department recorded them: initials in the lab, nicknames in pharmacy, occasional transposed letters in radiology, day/month-swapped birth dates. Nothing in the export links the accounts; identity resolution is any conversion's first problem.
- **Registration carries the chart.** Coverage (payer code, member number, relationship letter) and allergies are fields on the registration account record, not separate files.
- **The journal is the update channel.** Demographic changes after registration exist only as journal `C` entries against the registration account (`FIELD` of `ADDR` or `PHONE`, with the new value). Journal `D` entries mark records deleted in the source (entered-in-error results, test accounts).
- **Providers** are a flat file: code, name (`LAST,FIRST M CRED`), specialty as typed free text, NPI often blank.
- **Notes** are a header record followed by up to 8 continuation records of 72 characters. Radiology reports ride on the exam record (200 characters).

## The estate

The data files are only part of what a conversion team receives. The rest is documents and people, and they do not all agree with the data or with each other.

- **The data dictionary** (`DATADICT.TXT`, shipped in every export) is the vendor's own field-by-field description of the extracts. It is version 4.1, dated March 2019. The layouts it describes are version 5.0. It is mostly right.
- **The truth ledger** (`answer_key/estate_discrepancies.json`, written by the generator) records every deliberate discrepancy between the estate's documents and what the generator actually produces: what the document claims, what is true, and how the difference can be checked against the export. It exists so a future interview-driven onboarding process can be graded on what it catches. The dictionary and the analyst profiles never hint at which of their statements are the wrong ones.
- **Analyst profiles** (`testbed/delphi/analysts/`) are the knowledge of the four staff members a conversion team would interview: registration, laboratory, pharmacy, and the systems analyst who owns the dictionary. Each profile records the analyst's role and tenure, what they know well, what they do not know, what they believe that is wrong, and how they answer. The profiles are self-contained briefs; they are the only knowledge an analyst simulator may draw on, and they know nothing of planted issues or answer keys. The analysts disagree with each other on at least the pivot year and on what a duplicate chart means.

## Planted problems and scoring

The generator records every planted problem in `answer_key/issues.jsonl` in the same schema as Halcyon's, and `answer_key/persons.json` / `truth.json` follow Halcyon's shapes, so `testbed/scoring.py` can grade any future Delphi conversion unchanged. Issue types specific to this system include `century_window_dob` (a pre-1930 birth year read through the pivot), `cross_department_duplicate`, `duplicate_registration`, `truncated_name`, `name_variant`, `dob_variant`, `flag_string_result`, `lab_comparator_value`, `invalid_julian_date`, `julian_date_shift`, `invalid_time_minutes`, `shorthand_dx`, `free_text_dx`, `truncated_note`, `truncated_report` and `unrepresentable_status` (appointment status `R`), alongside the familiar `unmappable_medication`, `unmappable_lab`, `unmappable_charge`, `missing_discharge`, `unknown_visit_type`, `nka_conflict`, `missing_relationship`, `missing_dob`, `orphan_provider` and `npi_missing_billing` / `npi_invalid`. Rates are configurable in the generator's `Config`.

There are no vitals, immunization or user-account extracts. Vitals were kept on paper flowsheets. Immunizations were someone else's system. The vendor's position on both is available on request.

## Known limitations

From the vendor's own documentation, lightly abridged:

- Years are stored as two digits. The vendor describes this as forward compatible.
- Dates before 1930 are read as dates after 2020. The vendor notes that very few active patients were born before 1930, and that the list is getting shorter.
- Lab collection dates are stored as a two-digit year and a day of year. Arithmetic is left to the reader.
- Times are stored as minutes since midnight. Values above 1439 are handled on a case-by-case basis.
- Names longer than 30 characters are shortened. Patients with longer names have not complained, in writing, within 30 characters.
- Each department maintains its own patient numbering. Coordination between departments is available as a consulting engagement.
- Lab results carry their abnormal flag as a suffix, e.g. `12.4H`. Results that are not numbers are returned as prose, e.g. `FAXED TO MD`.
- Diagnoses may be recorded as shorthand. The shorthand dictionary is complete, in the sense that it contains all the shorthand the vendor has been told about.
- Notes are limited to eight lines of 72 characters. Clinicians requiring a ninth line are encouraged to be concise.
- The system stores text in uppercase. Lowercase is supported through a third-party module.
