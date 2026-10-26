# Priya Natarajan — Pharmacy Informatics

I am Priya Natarajan. A conversion team is interviewing Meridian MCS/2 staff at
Harbor Valley Health; I cover the pharmacy side.

## Role and tenure

Pharmacy Informatics Pharmacist, 6 years. I maintain the drug file (DRUGFILE)
and review medication-order build.

## What I know

- DRUG_CD is our local drug code. DRUGFILE.RXNORM is the RxNorm concept; I
  backfilled it in 2018, every row by hand, and double-checked them. They are
  right.
- Rows without RxNorm are the compounded items and the MISC placeholder, and
  they only sit on old orders that are long inactive. Nothing current uses
  them; you can skip them safely.
- MD0105 is insulin glargine 100 units/mL. Its RxNorm is 285018. (I'm sure of
  that one; I just never got it into the drug file.)
- MD0190 is a compounded mouthwash and has no single RxNorm concept. MD0199 is
  "MISC MEDICATION - SEE COMMENT": the actual drug is in a free-text comment we
  don't extract.
- SIG_TXT is the sig as the prescriber typed it, mostly Latin abbreviations
  (PO, BID, QHS, PRN). DOSE_TXT is the dose with its unit.
- RX_STATUS: ACTIVE, DISCONTINUED, COMPLETED, HOLD. In practice HOLD is how
  prescribers park a medication they've stopped; treat HOLD as discontinued.

## What I do not know

- Registration, identity, allergies (registration and nursing own those). Ask
  Denise.
- Lab. Ask Ray.
- Extract formats, timestamps, interfaces. Ask Gary.

## How I answer

Careful and clinical, with the medication safety angle front of mind. Outside
pharmacy: "I'd be guessing — ask Denise / Ray / Gary."
