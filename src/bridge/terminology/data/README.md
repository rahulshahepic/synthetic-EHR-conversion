# Bridge crosswalks (synthetic)

These tables are the conversion team's mapping work for Halcyon -> Nimbus. Standard code values
are illustrative and small; descriptions are our own. All codes in these files are **synthetic**:
invented where a real standard would be licensed content, and labeled as such here and in
`testbed/halcyon/vocab.py`. Gaps are deliberate: a local code that is missing here produces a
reconciliation question at run time (see docs/mapping-and-fidelity.md). Answers to questions
become run-scoped mapping rules; recurring answers should be promoted into these files
(task T-105).

## Coverage rule

Every local code the Halcyon generator can emit (the vocabularies in
`testbed/halcyon/vocab.py`, plus the Lakeside profile's visit types in
`testbed/halcyon/profiles/lakeside.py`, whose lab and formulary codes reuse the vocab codes)
either has a row in one of these CSVs or is listed below as a deliberate gap.
`tests/bridge/test_terminology_data.py` enforces this: it derives the code lists from the
vocabularies programmatically and fails if a code is neither mapped nor listed here.
`tools/crosswalk_gaps.py` lists the question kind+keys a conversion actually filed that a
crosswalk row could have prevented.

## Deliberate gaps

Each line is `- domain \`DOMAIN\`, key \`KEY\`` followed by why the code stays unmapped.
Text-keyed domains use the normalized (lower-cased, whitespace-collapsed) form of the source
text; `(blank)` means the empty source value.

- domain `local_dx`, key `HZ099` — "Non-compliance w/ treatment" (truth Z91.19). Sensitive,
  judgment-laden coding: team policy is that a human reviews every instance through the
  `unmapped_local_dx` question instead of Bridge auto-coding it. This is the intentional gap
  named in task T-105.
- domain `formulary`, key `HFORM0015` — compounded preparation ("magic mouthwash"); there is
  no single RxNorm concept for a locally compounded mixture (vocab truth is None).
- domain `formulary`, key `HFORM0099` — "MISC MED SEE NOTE" placeholder order; the actual
  medication lives in a free-text note, so no RxNorm row is possible (vocab truth is None).
- domain `lab`, key `XLAB7` — send-out miscellaneous test bucket; the real test (and its
  LOINC) is only known to the reference lab (vocab truth is None).
- domain `vaccine`, key `PPD` — a TB skin test is not a vaccine and has no CVX code (vocab
  truth is None); the `unmapped_vaccine` question's default drops it with a loss-ledger note.
- domain `visit_class`, key `XX` — Riverbend's uncoded visit bucket; the encounter class is
  unknown by definition (vocab truth is None), so a human picks it per run.
- domain `visit_class`, key `UNK` — Lakeside's uncoded visit bucket; same rationale as `XX`.
- domain `allergen`, key `bee stings` — inherently uncodable free text (vocab truth is None);
  loads as uncoded allergen text via the allergy mapper's degrade path.
- domain `allergen`, key `seasonal` — inherently uncodable free text (vocab truth is None);
  not a substance, so no substance code exists for it.
- domain `allergen`, key `grandma's casserole` — inherently uncodable free text (vocab truth
  is None); a household dish, not a codable substance.
- domain `specialty`, key `(blank)` — blank specialty text degrades to `other`, which is
  exactly the vocab truth for it; a CSV row keyed by the empty string would be invisible and
  fragile, so the default carries it.
- domain `race`, key `(blank)` — blank race text becomes `unknown` by the patient mapper's
  default, matching the vocab truth; same empty-key rationale as specialty.
- domain `free_text_dx`, key `bad back` — free-text problem description; no crosswalk file
  exists for free text. These flow through the `free_text_problem` question/rule mechanism
  by design (non-blocking, keep-as-text default; a run-scoped answer can still code them).
- domain `free_text_dx`, key `sugar` — free-text problem description; same `free_text_problem`
  rationale as above.
- domain `free_text_dx`, key `high cholesterol` — free-text problem description; same
  `free_text_problem` rationale as above.
- domain `free_text_dx`, key `nerves` — free-text problem description; same
  `free_text_problem` rationale as above.
- domain `free_text_dx`, key `h/o fall` — free-text problem description; same
  `free_text_problem` rationale as above.
- domain `charges`, key `HC9999` — "MISC SUPPLY" has no CPT/HCPCS in the source charge
  master (vocab truth is None). Charge codes are governed by that charge master, not by
  these CSVs, so the `unmapped_charge` question handles it instead.
