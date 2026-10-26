"""Meridian MCS/2 vocabularies (synthetic). Truth columns are for the answer key only.

All codes here are synthetic and illustrative: RxNorm/LOINC/ICD values reuse the same
small synthetic set Bridge's crosswalks use, so a correct conversion is checkable.
"""
from __future__ import annotations

SYSTEM_NAME = "Harbor Valley Health"

# campus code -> (name, city, state, true IANA zone, vital-sign unit system)
CAMPUSES = {
    "HVMC": ("HARBOR VALLEY MEDICAL CENTER", "LAS CRUCES", "NM", "America/Denver", "us"),
    "SRC": ("SUN RIDGE CLINIC", "TUCSON", "AZ", "America/Phoenix", "metric"),
}

# clinic code -> (name, campus)
CLINICS = {
    "HVFM": ("FAMILY MEDICINE", "HVMC"),
    "HVIM": ("INTERNAL MEDICINE", "HVMC"),
    "HVED": ("EMERGENCY DEPT", "HVMC"),
    "HV3W": ("3 WEST MED SURG", "HVMC"),
    "SRFM": ("SUN RIDGE FAMILY PRACTICE", "SRC"),
    "SRUC": ("SUN RIDGE URGENT CARE", "SRC"),
}

# visit type -> (truth Nimbus class, clinics it occurs in, documented in the extract guide?)
VISIT_TYPES = {
    "OP": ("ambulatory", ["HVFM", "HVIM", "SRFM"], True),
    "ER": ("emergency", ["HVED", "SRUC"], True),
    "IP": ("inpatient", ["HV3W"], True),
    "OBS": ("observation", ["HV3W"], True),
    "SDS": ("ambulatory", ["HVIM"], True),
    "TH": ("virtual", ["HVFM", "SRFM"], False),   # telehealth, added 2020, never documented
}

# specialty text as typed -> truth Nimbus specialty
SPECIALTIES = {
    "Family Practice": "family-medicine", "Internal Med": "internal-medicine", "Peds": "pediatrics",
    "ER": "emergency-medicine", "Hospitalist": "hospital-medicine", "Cardiology": "cardiology",
    "FNP": "nurse-practitioner", "PA-C": "physician-assistant", "Gen Surg": "general-surgery",
}

CARRIERS = {"BCX": "BLUE CANYON MUTUAL", "MCR": "MEDICARE", "AZC": "AZ COMPLETE CARE", "SLF": "SELF PAY"}
# plan code -> (carrier, name, plan type as stored)
PLANS = {
    "BCXPPO": ("BCX", "BLUE CANYON PPO", "PPO"),
    "BCXHMO": ("BCX", "BLUE CANYON HMO", "HMO"),
    "MCRA": ("MCR", "MEDICARE PART A/B", "MEDICARE"),
    "AZCMCD": ("AZC", "AZ COMPLETE MEDICAID", "MEDICAID"),
    "SELF": ("SLF", "SELF PAY", "SELF"),
}

# relationship code in the DATA -> canonical (X12) code. The extract guide documents S/SP/D/O.
REL_CODES = {"S": "18", "P": "01", "C": "19", "O": "G8"}

# registration race text (as typed) -> truth (race, ethnicity)
RACE_TEXT = {
    "White": ("white", None), "Black or African American": ("black-african-american", None),
    "Asian": ("asian", None), "Hispanic or Latino": (None, "hispanic-latino"),
    "American Indian/Alaska Native": ("american-indian-alaska-native", None),
    "Pacific Islander": ("native-hawaiian-pacific-islander", None),
    "Declined": ("asked-declined", None), "Other": ("other", None),
}

# problem list: (truth ICD-10, description, code system in source, source code as stored (no dot))
PROBLEMS = [
    ("E11.9", "TYPE 2 DIABETES", "I10", "E119"),
    ("I10", "ESSENTIAL HYPERTENSION", "I10", "I10"),
    ("E78.5", "HYPERLIPIDEMIA", "I10", "E785"),
    ("J45.909", "ASTHMA", "I10", "J45909"),
    ("F41.9", "ANXIETY", "I10", "F419"),
    ("K21.9", "GERD", "I10", "K219"),
    ("E03.9", "HYPOTHYROIDISM", "I10", "E039"),
    ("I48.91", "ATRIAL FIBRILLATION", "I10", "I4891"),
    ("M54.50", "LOW BACK PAIN", "I10", "M545"),         # retired code still on old problem lists
    ("E11.9", "DM II", "I9", "25000"),                  # pre-Oct-2015 ICD-9 entries
    ("I10", "HTN", "I9", "4019"),
    ("J44.9", "COPD", "I9", "496"),
    ("E66.9", "OBESITY", "I9", "27800"),
    ("M17.9", "OA KNEE", "I9", "71590"),                # ICD-9 1:many; truth is the knee code
    ("F32.A", "DEPRESSION", "I9", "311"),
]
FREE_TEXT_PROBLEMS = ["CHRONIC FATIGUE", "HX OF FALLS", "SOCIAL ISOLATION"]

# allergen text -> truth (system, code) or None (uncodable)
ALLERGENS = {
    "Penicillin": ("RxNorm", "7980"), "Sulfa": ("SNOMED-CT", "387406002"), "Codeine": ("RxNorm", "2670"),
    "Latex": ("SNOMED-CT", "111088007"), "Peanuts": ("SNOMED-CT", "256349002"),
    "Shellfish": ("SNOMED-CT", "227037002"), "IV Contrast": ("SNOMED-CT", "293637006"),
    "Aspirin": ("RxNorm", "1191"), "Bee stings": None, "Adhesive tape": None,
}
REACTIONS = ["Hives", "Rash", "Anaphylaxis", "SOB", "Rash; Itching", "Swelling", "Unknown", ""]
SEVERITY = ["SEVERE", "MODERATE", "MILD", ""]

# drug file: code -> (description, RxNorm in DRUGFILE (blank = not populated), truth RxNorm, doses, sigs)
DRUGS = {
    "MD0101": ("LISINOPRIL 10 MG TABLET", "314076", "314076", ["10 MG"], ["1 TAB PO DAILY", "TAKE 1 TABLET BY MOUTH DAILY"]),
    "MD0102": ("METFORMIN 500 MG TABLET", "861007", "861007", ["500 MG"], ["1 TAB PO BID", "1 TAB PO BID WITH MEALS"]),
    "MD0103": ("ATORVASTATIN 20 MG TABLET", "617312", "617312", ["20 MG"], ["1 TAB PO QHS"]),
    "MD0104": ("WARFARIN 5 MG TABLET", "855332", "855332", ["5 MG", "2.5 MG"], ["1 TAB PO DAILY", "UD PER INR CLINIC"]),
    "MD0105": ("INSULIN GLARGINE 100 UNIT/ML", "", "285018", ["10 UNITS", "22 UNITS"], ["10 UNITS SUBQ QHS"]),
    "MD0106": ("AMOXICILLIN 500 MG CAPSULE", "308191", "308191", ["500 MG"], ["1 CAP PO TID X10D"]),
    "MD0107": ("ALBUTEROL HFA 90 MCG INHALER", "745679", "745679", ["2 PUFFS"], ["2 PUFFS INH Q4-6H PRN SOB"]),
    "MD0108": ("LEVOTHYROXINE 50 MCG TABLET", "966222", "966222", ["50 MCG"], ["1 TAB PO QAM"]),
    "MD0109": ("OMEPRAZOLE 20 MG CAPSULE", "198053", "198053", ["20 MG"], ["1 CAP PO DAILY AC"]),
    "MD0110": ("SERTRALINE 50 MG TABLET", "312940", "312940", ["50 MG"], ["1 TAB PO DAILY"]),
    "MD0111": ("APIXABAN 5 MG TABLET", "1364445", "1364445", ["5 MG"], ["1 TAB PO BID"]),
    "MD0112": ("PREDNISONE 10 MG TABLET", "312615", "312615", ["40 MG"], ["4 TABS PO DAILY X5D"]),
    "MD0190": ("MAGIC MOUTHWASH COMPOUND", "", None, ["10 ML"], ["SWISH AND SPIT 10ML QID PRN"]),
    "MD0199": ("MISC MEDICATION - SEE COMMENT", "", None, [""], ["SEE COMMENT"]),
}
RX_STATUS = {"ACTIVE": "active", "DISCONTINUED": "stopped", "COMPLETED": "completed", "HOLD": "on-hold"}

# test code -> (name, LOINC in TESTDICT (blank = none), truth LOINC, unit, (lo, hi), ref text, value kind)
TESTS = {
    "GLUC": ("GLUCOSE", "2345-7", "2345-7", "mg/dL", (70, 180), "70-99", "num"),
    "K": ("POTASSIUM", "2823-3", "2823-3", "mEq/L", (3.2, 5.6), "3.5-5.1", "num"),
    "NA": ("SODIUM", "2951-2", "2951-2", "mEq/L", (132, 146), "136-145", "num"),
    "CR": ("CREATININE", "2160-0", "2160-0", "mg/dL", (0.6, 1.8), "0.6-1.2", "num"),
    "A1C": ("HEMOGLOBIN A1C", "4548-4", "4548-4", "%", (5.0, 9.5), "<5.7", "num"),
    "CHOL": ("CHOLESTEROL", "2093-3", "2093-3", "mg/dL", (140, 260), "<200", "num"),
    "LDL": ("LDL CALC", "13457-7", "13457-7", "mg/dL", (60, 190), "<100", "num"),
    "WBC": ("WBC", "6690-2", "6690-2", "K/uL", (3.5, 13.0), "4.0-11.0", "num"),
    "HGB": ("HEMOGLOBIN", "718-7", "718-7", "g/dL", (10.0, 17.0), "12.0-16.0", "num"),
    "TSH": ("TSH", "3016-3", "3016-3", "mIU/L", (0.3, 6.0), "0.4-4.0", "num"),
    "INR": ("INR", "6301-6", "6301-6", "", (0.9, 3.5), "0.8-1.2", "num"),
    "RSTREP": ("RAPID STREP", "78012-2", "78012-2", "", None, "NEG", "posneg"),
    "SENDOUT": ("SEND OUT MISC", "", None, "", None, "", "text"),
}

VITAL_TYPES = ["BP", "HR", "RR", "TEMP", "WT", "HT", "SPO2"]
# VS_TYPE -> Bridge vital field (the binding the interview has to establish)
VITAL_FIELD = {"BP": "BP", "HR": "PULSE", "RR": "RESP", "TEMP": "TEMP", "WT": "WT", "HT": "HT", "SPO2": "SPO2"}

# appointment status in the DATA -> truth Nimbus status (None: no Nimbus equivalent). Guide documents 5.
APPT_STATUS = {"SCH": "booked", "ARR": "arrived", "CMP": "fulfilled", "NOS": "noshow", "CAN": "cancelled", "BMP": None}

LAST_NAMES = ["GARCIA", "NAKAMURA", "OKAFOR", "MARTINEZ", "BEGAY", "NGUYEN", "SMITH", "JOHNSON", "LOPEZ", "YAZZIE",
              "PATEL", "KIM", "HERNANDEZ", "WILSON", "TSOSIE", "ANDERSON", "RAMIREZ", "CHAVEZ", "BROWN", "TORRES",
              "O'NEIL", "DE LA CRUZ", "MCALLISTER", "VALENZUELA", "WHITEHORSE", "SANDOVAL", "LEE", "MORALES"]
FIRST_M = ["JAMES", "ROBERT", "MICHAEL", "JOSE", "DAVID", "DANIEL", "LUIS", "ETHAN", "NOAH", "JULIAN", "AARON", "TOMAS"]
FIRST_F = ["MARIA", "MARY", "ELENA", "SARAH", "LINDA", "JENNIFER", "ANA", "GRACE", "SOFIA", "ROSA", "NAOMI", "CARMEN"]
NICK = {"JAMES": "JIM", "ROBERT": "BOB", "MICHAEL": "MIKE", "MARY": "MARIE", "DANIEL": "DANNY", "ELENA": "LENA"}
STREETS = ["MESA VERDE DR", "SAGUARO LN", "EL PASEO RD", "CANYON VIEW CT", "MAIN ST", "DESERT WILLOW WAY", "PALO VERDE AVE"]
CITIES = {"HVMC": [("LAS CRUCES", "NM", "880"), ("MESILLA", "NM", "880")], "SRC": [("TUCSON", "AZ", "857"), ("MARANA", "AZ", "856")]}
