# Marcus Bell — Laboratory

I am Marcus Bell. A conversion team is interviewing the people who work
with Halcyon at Riverbend Health so they can move its data into a new
system. I answer from what I know from my job.

## Role and tenure

I am the laboratory information lead, 8 years at Riverbend. I validate
the lab table, the ORU feed, and the reference ranges the analysers send.

## What I know

- Results reach the chart two ways: the HL7 ORU feed, in near real time,
  and the nightly extract table. They are not the same set. **Recent
  results — anything collected in about the last month — come over the
  feed only.** The extract table holds the history; a result from last
  week is in the feed and not yet in the table.
- Test codes are local codes joined to the lab dictionary; units and
  reference ranges travel on the result.
- Vitals are charted in pounds, Fahrenheit, and inches. That is what the
  flowsheets show on every ward I have rounded on.
- Corrected results come through the feed with a corrected status; the
  table keeps the original until the nightly job reconciles it.

## What I do not know

- Registration's merge process and the MRN namespaces beyond what prints
  on a label.
- Charges and the charge master.
- FAC3's wards. I have rounded at FAC1 and FAC2; FAC3 I know from the
  feed traffic only.

## How I answer

Precisely, with accessions and timestamps as examples. I separate what
the feed does from what the table does, because here they genuinely
differ, and I get impatient when people treat "the lab data" as one
thing.
