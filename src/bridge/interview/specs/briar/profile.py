"""GENERATED profile for briar by the Socratic import builder.

Artifact of record: the declarative spec (spec.json) this was rendered
from. Do not edit by hand; re-run the interview/spec generation.
"""

SOURCE_SYSTEM = 'briar'
READER = 'fixed_width'

# Known unknowns: unresolved at generation time. Each becomes a
# runtime reconciliation question, never a silent default.
KNOWN_UNKNOWNS = [{'subject': 'field:APPT.TXT.STATUS', 'predicate': 'convention', 'claimed_values': [{'B': 'booked', 'C': 'cancelled', 'R': 'rescheduled'}, {'B': 'booked', 'C': 'cancelled', 'R': 'arrived'}], 'disposition': 'runtime_question'}, {'subject': 'identity', 'predicate': 'merge_decisions', 'disposition': 'runtime_question', 'note': 'Every proposed identity merge is decided by a human in reconciliation; the spec contains no auto-merge rule.'}]

# Identity merges require a human decision (policy; see spec).
MERGE_POLICY = "route_to_reconciliation"
