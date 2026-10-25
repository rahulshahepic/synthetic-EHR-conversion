# The Halcyon estate

This file lives OUTSIDE the estate root on purpose: it is meta-commentary
about the estate (which source wins, where grading lives), and a document
like that must never be servable through the estate reader.

What a conversion team actually receives for Halcyon, assembled for the
Socratic import builder (docs/socratic-import-builder.md, T-120):

- `estate/dictionary_excerpts.md` — the IT dictionary's relevant excerpts.
  Mostly right; stale in specific places.
- `estate/interface_notes.md` — the interface team's notes. Correct where
  the dictionary is stale, because they were written from the traffic.
- `analysts/` — four first-person analyst profiles (HIM/registration,
  laboratory, pharmacy, interface engineering). Beliefs are stated as the
  analysts state them; nothing flags which are wrong.
The grading ledger — every deliberate discrepancy between the estate's
documents/people and the system as built, with how to check it — is NOT
an estate document and does not live here: it is in `grading/`
(`testbed/halcyon/grading/estate_discrepancies.json`), outside every
estate root the builder can read, and the estate firewall denies it by
name as well. It is copied into an export's answer-key directory when an
estate is assembled for grading; Bridge code never reads it.
