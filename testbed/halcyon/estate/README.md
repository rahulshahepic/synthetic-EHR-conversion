# The Halcyon estate

What a conversion team actually receives for Halcyon, assembled for the
Socratic import builder (docs/socratic-import-builder.md, T-120):

- `dictionary_excerpts.md` — the IT dictionary's relevant excerpts. Mostly
  right; stale in specific places.
- `interface_notes.md` — the interface team's notes. Correct where the
  dictionary is stale, because they were written from the traffic.
- `../analysts/` — four first-person analyst profiles (HIM/registration,
  laboratory, pharmacy, interface engineering). Beliefs are stated as the
  analysts state them; nothing flags which are wrong.
- `estate_discrepancies.json` — the grading ledger: every deliberate
  discrepancy between the estate's documents/people and the system as
  built, with how to check it. This file is grading truth. It is copied
  into an export's answer-key directory when an estate is assembled for
  grading; Bridge code never reads it.
