"""Source profile for Halcyon Classic: facts the conversion team learned from the source system's
documentation and site interviews (manifest notes, facility conventions). Not ground truth."""
from datetime import date

SYSTEM_ORG = {"key": "SYS-RIVERBEND", "name": "Riverbend Health"}
MRN_SYSTEM = "urn:halcyon:mrn:{fac}"
FACILITY_TZ = {"FAC1": "America/Chicago", "FAC2": "America/Chicago", "FAC3": "America/Denver"}
DEFAULT_TZ = "America/Chicago"
# VITALS have no unit columns; units depend on facility.
VITAL_UNITS = {
    "FAC1": {"WT": "[lb_av]", "TEMP": "[degF]", "HT": "[in_i]"},
    "FAC2": {"WT": "[lb_av]", "TEMP": "[degF]", "HT": "[in_i]"},
    "FAC3": {"WT": "kg", "TEMP": "Cel", "HT": "cm"},
}
CHARGE_CENTS_FROM = date(2012, 1, 1)  # AMOUNT in dollars before, integer cents on/after
LAB_FEED_ONLY_DAYS = 30
