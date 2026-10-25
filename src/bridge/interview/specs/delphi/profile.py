"""GENERATED profile for delphi by the Socratic import builder.

Artifact of record: the declarative spec (spec.json) this was rendered
from. Do not edit by hand; re-run the interview/spec generation.
"""

SOURCE_SYSTEM = 'delphi'
READER = "fixed_width"
# provenance: analyst — ledger:E000032 (Marla Denny, registration); dispute resolved via OBS-0126 + ledger answer (Marla Denny, registration): window starts 1930 (data_confirmed=True)
PIVOT_YEAR = 30

# Known unknowns: unresolved at generation time. Each becomes a
# runtime reconciliation question, never a silent default.
KNOWN_UNKNOWNS = [{'subject': 'field:APPT.TXT.STATUS', 'predicate': 'convention', 'claimed_values': ['one of B, C, N, A, X', 'B, C, N, A, X, and R (R undocumented, present in the data)'], 'disposition': 'runtime_question'}, {'subject': 'field:LAB.TXT.RESULT', 'predicate': 'convention', 'claimed_values': ['numeric value with optional flag suffix; non-numeric values are bench errors and are excluded', 'mixed numeric and non-numeric values: 10.8% of values are non-numeric text (samples: <, ABNORMAL C, FAXED TO M, NEG, PENDING RE); non-numeric values are present in the data and carried as text'], 'disposition': 'runtime_question'}, {'subject': 'identity', 'predicate': 'merge_decisions', 'disposition': 'runtime_question', 'note': 'Every proposed identity merge is decided by a human in reconciliation; the spec contains no auto-merge rule.'}]

# Identity merges require a human decision (policy; see spec).
MERGE_POLICY = "route_to_reconciliation"
