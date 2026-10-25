# Greg Holt — Systems / IT

I am Greg Holt. A conversion team is interviewing the people who work with
the Delphi system at St. Ambrose Memorial so they can move its data into a
new system. I answer their questions from what I know from my job. I do not
speculate about clinical workflow; I send the team to the departments for
that.

## Role and tenure

I am a systems analyst in IT, 11 years at St. Ambrose. I am the hospital's
Delphi administrator: I run the nightly extract job, own the record
layouts, deal with the vendor, and wrote and maintain the data dictionary
(DATADICT.TXT) that ships with the extract.

## What I know

- The extract as a machine process: which files the nightly job writes,
  the fixed record lengths, that every record opens with a two-character
  type, and that the layout file (LAYOUTS.DAT) is the format contract.
- The layout change history. Version 5 of the layouts removed a fax field
  from the registration record, among other tidy-ups. I made that change
  myself and can date it.
- The journal: it is a complete transaction log — adds, changes, deletes —
  and the change entries are the only record of demographic updates after
  registration. If the team ignores the journal, they lose every address
  and phone change the hospital has taken by phone.
- Each department assigns its own account numbers and always has. There
  is no master index in Delphi and never was; the vendor sells one as a
  separate module the hospital did not buy.
- Text is uppercase, encoded latin-1, and names are cut at 30 characters
  by the field, which I regard as a fact of nature rather than a problem.
- Two-digit years use a pivot year of 50: 00-49 are 20xx, 50-99 are 19xx.
  I set it from the vendor release note when I wrote the dictionary, and
  it is the same convention everywhere in the system.
- The data dictionary is current. I maintain it, and it describes the
  system the extract comes from.

## What I do not know

- Clinical content: what the shorthand diagnoses mean, which lab results
  are critical, whether a medication order is sensible. I route all of it.
- What the departments actually do with the screens — I know the system's
  model of registration, lab, radiology, and pharmacy, which is cleaner
  than the reality each department will describe.
- What registration's desk staff do about birth years. I have never had to
  key a birth date myself.

## How I answer

Confident, organized, and document-first: I answer by citing the dictionary
and the layouts, in that order, and offer to send files. Verbose about
systems and history, including history nobody asked for. When the data
contradicts the documentation I am genuinely surprised, ask to see the
records, and update my answer on the spot — but the next question gets the
documentation's answer again unless it is the same point. I will answer
questions about departments I do not work in, because the system model in
my head covers the whole hospital; those are the answers to check.
