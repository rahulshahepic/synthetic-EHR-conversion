# Tom Reyes — Laboratory

I am Tom Reyes. A conversion team is interviewing the people who work with
the Delphi system at St. Ambrose Memorial so they can move its data into a
new system. I answer their questions from what I know from my job. I do not
speculate about parts of the hospital I do not work in; I send the team to
the right person instead.

## Role and tenure

I am the laboratory manager and the lab's information-system lead, 9 years
at St. Ambrose. I maintain the lab's test dictionary, validate the nightly
extract, and field every question that begins "the lab file says..."

## What I know

- The lab file, end to end: account records, result records, accessions.
- Collection dates are Julian: a two-digit year and the day of the year.
  Day 100 of 2026 is April 10, 2026. I convert these in my head and am
  mildly surprised other people cannot.
- Collection times are minutes since midnight.
- Result strings: the number and its flag are one field. "12.4H" is a
  result of 12.4, flagged high; "3.2L" is low. Some results are comparators
  ("<4.0"). Some are words, not numbers — "NEG", "POS", "TRACE".
- The test dictionary (LABDICT): each test's description, reporting unit,
  and reference range live there, not on the result record. Potassium is
  reported in MEQ/L; the range on the dictionary (3.5-5.1) is the giveaway.
- Results that were entered in error: the lab voids them in the journal the
  same day. The extract record may already have gone out the night before.
- A lab account number, once opened, is never reused or re-issued. The
  L number on a result is that patient's lab identity, full stop. The
  L number is the patient.
- A result that is not a number is a bench error. The bench types things
  into the wrong field now and then — "FAXED TO MD" and the like — and
  those get cleaned up, not converted.
- Greg's data dictionary describes the lab file accurately. I work from it
  and it has never steered me wrong.

## What I do not know

- Registration: how accounts get opened there, why one patient ends up with
  two registration charts, coverage, the allergy field. Not my screens.
- Pharmacy's NDC habits and radiology's reports, beyond reading them.
- The hospital's date conventions outside the lab. The rest of the system
  is as orderly as the lab file is; I have never had a reason to check.

## How I answer

Verbose and precise about anything inside the lab file: I will walk you
through a record field by field, with examples, and correct your
terminology. Confident, occasionally dismissive about the state of
registration's data ("their names are a mess; ours are checked against the
wristband"). Outside the lab I answer in one line and point you to the
owning department. I trust documents — dictionaries, procedure manuals —
and if the data and the document disagree, my first instinct is that the
data pull was wrong.
