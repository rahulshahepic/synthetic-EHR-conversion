"""The Lakeside profile: a second source system with different conventions (T-108).

"Lakeside Health" is an invented two-site clinic system on its own Halcyon
install. Where Riverbend (the default profile) charts in US units with terse
Latin-abbreviation sigs and one set of visit codes, Lakeside charts metric,
writes sigs out as full English sentences, and uses its own visit codes.
Both systems feed the same Bridge, so if a run's input ever starts arriving
in Lakeside style mid-run, the distributions of units, visit codes, and sig
text shift measurably — which is exactly what drift monitors exist to catch.

Concrete differences from the default profile:

- **Units (metric).** Facilities chart kg / degC / cm. Lab overrides below
  restate each affected test in metric conventions, numeric ranges included:
  glucose and lipids in mmol/L (e.g. GLU reference range 3.9-5.5, not
  70-99 mg/dl), creatinine in umol/L, hemoglobin in g/L, cell counts in
  10*9/L, vitamin D in nmol/L. Electrolytes come out as mmol/L, never MEQ/L.
- **Visit codes.** EST/NEW (established/new outpatient), URG (urgent care),
  DAY (day-stay observation), VID (video visit), UNK (uncoded) — none of
  them collide with Riverbend's OV/OVN/ER/IP/OBS/TEL/XX.
- **Sig style.** Every formulary sig is a full sentence: spelled-out
  frequency and duration ("twice daily", "for 10 days", "as needed"),
  no po/bid/tid/qid/qhs/qd, no "x10d". Compare the default pool, where
  roughly half the variants are abbreviation-style ("1 TAB PO QD").
- **Rates.** Lakeside coders leave the visit type uncoded more often
  (``visit_xx`` 0.01 -> 0.03), so UNK shows up at triple the default rate.

All codes, names, and conversions are invented/standard-unit arithmetic and
labeled synthetic, per the repo's ground rules.
"""
from __future__ import annotations

from . import FacilityProfile

# id, name, tz, weight unit, temp unit, height unit — both sites are metric.
LAKESIDE_FACILITIES = (
    ("FAC9", "Lakeside Medical Center", "America/Denver", "kg", "C", "cm"),
    ("FAC8", "Lakeside Northgate Clinic", "America/Denver", "kg", "C", "cm"),
)

# dept id, facility (None = shared across facilities), name, kind
LAKESIDE_DEPTS = (
    ("D300", "FAC9", "LAKESIDE FAMILY MEDICINE", "clinic"),
    ("D310", "FAC9", "LAKESIDE URGENT CARE", "clinic"),
    ("D320", "FAC8", "NORTHGATE CLINIC", "clinic"),
    ("D900", None, "LAKESIDE LAB", "lab"),          # shared
    ("D910", None, "TELEHEALTH", "virtual"),        # shared
)

# Lakeside is a clinic system: urgent care absorbs the emergency-class
# traffic and day-stay the observation-class; there is no inpatient class.
LAKESIDE_CLASS_DEPTS = {"emergency": "D310", "observation": "D310", "virtual": "D910"}

# local code -> (truth class, weight). UNK's class is None: it is the
# uncoded bucket, planted further by the visit_xx rate below.
LAKESIDE_VISIT_TYPES = {
    "EST": ("ambulatory", 45), "NEW": ("ambulatory", 10), "URG": ("emergency", 12),
    "DAY": ("observation", 8), "VID": ("virtual", 15), "UNK": (None, 1),
}

# vocab.LABS-shaped rows restated in Lakeside conventions:
# code -> (description, truth LOINC, unit, kind, normal range, typical range).
# Tests without a row here (HGBA1C %, TSH mIU/L, INR, coded/text tests) use
# the same conventions in both systems and fall through to vocab.LABS.
LAKESIDE_LABS = {
    "GLU": ("GLUCOSE", "2345-7", "mmol/L", "num", (3.9, 5.5), (3.3, 16.7)),
    "K": ("POTASSIUM", "2823-3", "mmol/L", "num", (3.5, 5.1), (2.8, 6.2)),
    "NA": ("SODIUM", "2951-2", "mmol/L", "num", (136, 145), (125, 150)),
    "CREAT": ("CREATININE", "2160-0", "umol/L", "num", (53, 106), (35, 354)),
    "CHOL": ("CHOLESTEROL TOTAL", "2093-3", "mmol/L", "num", (0, 5.2), (3.1, 8.3)),
    "LDL": ("LDL CHOLESTEROL", "13457-7", "mmol/L", "num", (0, 2.6), (1.3, 5.7)),
    "HDL": ("HDL CHOLESTEROL", "2085-9", "mmol/L", "num", (1.0, 5.2), (0.6, 2.3)),
    "WBC": ("WHITE BLOOD COUNT", "6690-2", "10*9/L", "num", (4.0, 11.0), (2.0, 20.0)),
    "HGB": ("HEMOGLOBIN", "718-7", "g/L", "num", (120, 175), (70, 180)),
    "PLT": ("PLATELETS", "777-3", "10*9/L", "num", (150, 400), (50, 600)),
    "VITD": ("VITAMIN D 25-OH", "1989-3", "nmol/L", "num", (75, 250), (20, 200)),
}

# Formulary code -> Lakeside house-style sigs: full sentences, spelled-out
# frequency/duration/prn, no Latin abbreviations. Covers every FORMULARY
# code so no Riverbend-style sig leaks into a Lakeside export.
LAKESIDE_SIGS = {
    "HFORM0001": ["take 1 tablet by mouth once daily", "take one tablet by mouth every morning"],
    "HFORM0002": ["take 1 tablet by mouth twice daily with meals", "take 1 tablet by mouth two times daily"],
    "HFORM0003": ["take 1 tablet by mouth at bedtime", "take 1 tablet by mouth nightly"],
    "HFORM0004": ["take 1 tablet by mouth once daily", "take one half tablet by mouth at bedtime",
                  "take as directed per INR clinic"],
    "HFORM0005": ["inject 10 units under the skin at bedtime", "inject 22 units subcutaneously at bedtime"],
    "HFORM0006": ["take 1 capsule by mouth three times daily for 10 days",
                  "take 1 capsule by mouth every 8 hours for 10 days"],
    "HFORM0007": ["inhale 2 puffs every 4 to 6 hours as needed for shortness of breath",
                  "inhale 2 puffs every 4 hours as needed for wheezing"],
    "HFORM0008": ["take 1 tablet by mouth once daily before breakfast", "take 1 tablet by mouth every morning"],
    "HFORM0009": ["take 1 capsule by mouth once daily before breakfast", "take 1 capsule by mouth every morning"],
    "HFORM0010": ["take 1 to 2 tablets by mouth every 6 hours as needed for pain",
                  "take 1 tablet by mouth every 4 to 6 hours as needed for pain"],
    "HFORM0011": ["take 1 tablet by mouth twice daily", "take 1 tablet by mouth two times daily"],
    "HFORM0012": ["take 1 tablet by mouth once daily", "take 1 tablet by mouth every morning"],
    "HFORM0013": ["take 1 tablet by mouth three times daily as needed for pain, with food",
                  "take 1 tablet by mouth every 8 hours as needed for pain"],
    "HFORM0014": ["taper as directed", "take 4 tablets by mouth once daily for 5 days"],
    "HFORM0015": ["swish and spit 10 mL four times daily as needed", "swish and spit 10 mL every 6 hours as needed"],
    "HFORM0099": ["see note"],
}

LAKESIDE_PROFILE = FacilityProfile(
    name="lakeside",
    sender="LAKESIDE",
    facilities=LAKESIDE_FACILITIES,
    depts=LAKESIDE_DEPTS,
    facility_weights=(("FAC9", 3), ("FAC8", 1)),
    visit_types=LAKESIDE_VISIT_TYPES,
    unknown_visit_code="UNK",
    class_depts=dict(LAKESIDE_CLASS_DEPTS),
    lab_overrides=dict(LAKESIDE_LABS),
    sig_variants=dict(LAKESIDE_SIGS),
    # Lakeside coders leave visit type uncoded (UNK) more often.
    rates={"visit_xx": 0.03},
    manifest_notes={
        "timestamps": "Facility local time, no offset. FAC8/FAC9 US Mountain.",
        "units": "VITALS have no unit columns; FAC8/FAC9 record kg/degC/cm. Labs use metric units (mmol/L, umol/L, g/L).",
        "charges": "AMOUNT is dollars (with decimals) before 2012-01-01, integer cents after.",
        "feeds": "HL7 v2.3. ADT A08 newer than PAT; A40 = merge (MRG = retired MRN). ORU: last 30 days only in feed.",
    },
)
