# Halcyon Classic — Data Dictionary (excerpts)

Maintained by IT Clinical Systems. Excerpts relevant to a conversion
extract; the full dictionary lives on the shared drive.

## Organisation and identifiers

- The system organisation is **Riverbend Health** (key SYS-RIVERBEND).
- The medical record number is namespaced per facility:
  `urn:halcyon:mrn:{fac}` where `{fac}` is the facility code
  (FAC1, FAC2, FAC3).
- All facilities run on **America/Chicago** time. Timestamps in the
  database and in HL7 messages are facility local time.

## Vitals

Vitals carry no unit columns. Units are facility convention, and the
convention is uniform across Riverbend: weight in pounds (`[lb_av]`),
temperature in Fahrenheit (`[degF]`), height in inches (`[in_i]`).

## Charges

`AMOUNT` on a charge line is an **integer number of cents** — it has
always been cents — joined to the charge master on `CHG_CODE`.

## Laboratory

Laboratory results live in the `LAB_RESULT` table and are included in
full in the nightly CSV extract. Results also arrive over the HL7 ORU
interface in real time; the feed and the extract carry the same results,
and the extract is the complete record.
