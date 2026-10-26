"""GENERATED profile for meridian by the Socratic import builder.

Artifact of record: the declarative spec (spec.json) this was rendered
from. Do not edit by hand; re-run the interview/spec generation.
"""

SOURCE_SYSTEM = 'meridian'
READER = 'delimited'
# provenance: dictionary — MCS2_EXTRACT_GUIDE.TXT v3.2 (estate) §1 (data_confirmed=False)
DEFAULT_TZ = 'America/Denver'
# provenance: analyst — ledger:E000154 (Gary Lindqvist, interface); dispute resolved via ledger:E000154 (Gary Lindqvist, interface) + OBS-0018 (CAMPUS.STATE: SRC is in AZ; Arizona does not observe DST). Denise's one-clock answer (E000186) repeats the stale guide. (data_confirmed=True)
FACILITY_TZ = {'HVMC': 'America/Denver', 'SRC': 'America/Phoenix'}
# provenance: dictionary — MCS2_EXTRACT_GUIDE.TXT v3.2 (estate) §4 (PERSON.MRN enterprise medical record number) (data_confirmed=False)
MRN_SYSTEM = 'urn:meridian:mrn'
# provenance: dictionary — KICKOFF_MEMO.TXT (estate) (data_confirmed=False)
SOURCE_NAME = 'Meridian'
# provenance: dictionary — KICKOFF_MEMO.TXT (estate) (data_confirmed=False)
SYSTEM_ORG = {'key': 'SYS-HARBORVALLEY', 'name': 'Harbor Valley Health'}
# provenance: analyst — ledger:E000160 (Gary Lindqvist, interface) (data_confirmed=True)
VITAL_UNITS = {'HVMC': {'HT': '[in_i]', 'TEMP': '[degF]', 'WT': '[lb_av]'}, 'SRC': {'HT': 'cm', 'TEMP': 'Cel', 'WT': 'kg'}}

# Source code sets -> standard codes, as the interview established them.
# provenance formulary: dictionary — DRUGFILE.DAT RXNORM column (estate) + MD0105 from ledger:E000206 (Priya Natarajan, pharmacy) (data_confirmed=False)
# provenance labs: dictionary — TESTDICT.DAT LOINC column (estate), loaded by Ray Castillo (ledger:E000198) (data_confirmed=False)
# provenance race: analyst — ledger:E000176 (Denise Okafor, registration) (data_confirmed=False)
# provenance visit_class: analyst — ledger:E000158 (Gary Lindqvist, interface) (data_confirmed=False)
CROSSWALKS = {'formulary': {'MD0101': '314076', 'MD0102': '861007', 'MD0103': '617312', 'MD0104': '855332', 'MD0105': '285018', 'MD0106': '308191', 'MD0107': '745679', 'MD0108': '966222', 'MD0109': '198053', 'MD0110': '312940', 'MD0111': '1364445', 'MD0112': '312615'}, 'labs': {'A1C': '4548-4', 'CHOL': '2093-3', 'CR': '2160-0', 'GLUC': '2345-7', 'HGB': '718-7', 'INR': '6301-6', 'K': '2823-3', 'LDL': '13457-7', 'NA': '2951-2', 'RSTREP': '78012-2', 'TSH': '3016-3', 'WBC': '6690-2'}, 'race': {'American Indian/Alaska Native': 'american-indian-alaska-native', 'Asian': 'asian', 'Black or African American': 'black-african-american', 'Declined': 'asked-declined', 'Hispanic or Latino': '|hispanic-latino', 'Other': 'other', 'Pacific Islander': 'native-hawaiian-pacific-islander', 'White': 'white'}, 'visit_class': {'ER': 'emergency', 'IP': 'inpatient', 'OBS': 'observation', 'OP': 'ambulatory', 'SDS': 'ambulatory', 'TH': 'virtual'}}

# Known unknowns: unresolved at generation time. Each becomes a
# runtime reconciliation question, never a silent default.
KNOWN_UNKNOWNS = [{'subject': 'field:APPT.DAT.APPT_STATUS', 'predicate': 'convention', 'claimed_values': ['SCH, ARR, CMP, NOS, CAN', 'observed values SCH, ARR, CMP, NOS, CAN and BMP (26 rows); BMP is not in the guide'], 'disposition': 'runtime_question'}, {'subject': 'identity', 'predicate': 'merge_decisions', 'disposition': 'runtime_question', 'note': 'Every proposed identity merge is decided by a human in reconciliation; the spec contains no auto-merge rule.'}]

# Identity merges require a human decision (policy; see spec).
MERGE_POLICY = "route_to_reconciliation"
