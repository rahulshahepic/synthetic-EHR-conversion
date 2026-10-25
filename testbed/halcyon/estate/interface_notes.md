# Interface and site notes (excerpts)

Collected by the interface team from the HL7 build and site visits.

- Feeds: ADT (A01/A03/A08/A40) and ORU result messages, Mirth channels per
  facility. The database extract (SQLite plus CSVs) is generated nightly
  from the same system.
- FAC3 is the Denver site. It runs **Mountain Time (America/Denver)** and
  its charting is metric — weights in kilograms, temperatures in Celsius,
  heights in centimetres. FAC1 and FAC2 are Central and imperial.
- Billing: the 2012 billing upgrade moved charge amounts to integer
  cents. Anything keyed before the upgrade is in dollars.
- The charge extract joins the charge master on `CHG_CODE`; codes are
  local and stable.
