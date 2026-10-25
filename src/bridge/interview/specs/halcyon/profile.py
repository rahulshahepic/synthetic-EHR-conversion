"""GENERATED profile for halcyon by the Socratic import builder.

Artifact of record: the declarative spec (spec.json) this was rendered
from. Do not edit by hand; re-run the interview/spec generation.
"""
from datetime import date

SOURCE_SYSTEM = 'halcyon'
READER = "halcyon"
# provenance: analyst — dispute resolved via OBS-ESTATE-2 + ledger answer (Tom Okafor, interface engineering) (data_confirmed=False)
CHARGE_CENTS_FROM = date(2012, 1, 1)
# provenance: dictionary — Halcyon interface notes (estate); dispute resolved via OBS-ESTATE-1 + ledger answer (Tom Okafor, interface engineering) (data_confirmed=False)
FACILITY_TZ = {'FAC1': 'America/Chicago', 'FAC2': 'America/Chicago', 'FAC3': 'America/Denver'}
# provenance: dictionary — Halcyon dictionary excerpts (estate) (data_confirmed=False)
MRN_SYSTEM = 'urn:halcyon:mrn:{fac}'
# provenance: dictionary — Halcyon dictionary excerpts (estate) (data_confirmed=False)
SYSTEM_ORG = {'key': 'SYS-RIVERBEND', 'name': 'Riverbend Health'}
# provenance: dictionary — Halcyon interface notes (estate); dispute resolved via OBS-ESTATE-1 + ledger answer (Tom Okafor, interface engineering) (data_confirmed=False)
VITAL_UNITS = {'FAC1': {'HT': '[in_i]', 'TEMP': '[degF]', 'WT': '[lb_av]'}, 'FAC2': {'HT': '[in_i]', 'TEMP': '[degF]', 'WT': '[lb_av]'}, 'FAC3': {'HT': 'cm', 'TEMP': 'Cel', 'WT': 'kg'}}

# Known unknowns: unresolved at generation time. Each becomes a
# runtime reconciliation question, never a silent default.
KNOWN_UNKNOWNS = [{'subject': 'profile', 'predicate': 'lab_feed_only_days', 'claimed_values': [0, 30], 'disposition': 'runtime_question'}, {'subject': 'identity', 'predicate': 'merge_decisions', 'disposition': 'runtime_question', 'note': 'Every proposed identity merge is decided by a human in reconciliation; the spec contains no auto-merge rule.'}]

# Identity merges require a human decision (policy; see spec).
MERGE_POLICY = "route_to_reconciliation"
