"""Halcyon local vocabularies with the *true* meaning of each code.

The truth columns (LOINC/RxNorm/ICD-10/CVX/CPT) are what a perfect conversion would produce.
They exist so tests can score Bridge; Bridge itself must build its own crosswalks.
Standard code values are illustrative; descriptions are our own (synthetic).
"""

FACILITIES = [
    # id, name, tz, weight unit, temp unit, height unit
    ("FAC1", "Riverbend General Hospital", "America/Chicago", "lb", "F", "in"),
    ("FAC2", "Riverbend North Clinic", "America/Chicago", "lb", "F", "in"),
    ("FAC3", "Lakeside Family Practice", "America/Denver", "kg", "C", "cm"),
]

# dept id, facility (None = shared across facilities), name, kind
DEPTS = [
    ("D100", "FAC1", "EMERGENCY DEPT", "ed"),
    ("D110", "FAC1", "MED/SURG 3W", "inpatient"),
    ("D120", "FAC1", "CARDIOLOGY CLINIC", "clinic"),
    ("D130", "FAC1", "ENDOCRINE CLINIC", "clinic"),
    ("D200", "FAC2", "FAMILY MED NORTH", "clinic"),
    ("D210", "FAC2", "PEDIATRICS NORTH", "clinic"),
    ("D300", "FAC3", "LAKESIDE FP", "clinic"),
    ("D900", None, "RIVERBEND LAB", "lab"),          # shared: no single site in Nimbus
    ("D910", None, "TELEHEALTH", "virtual"),        # shared
]

SPECIALTY_TEXT = {  # free text variants -> truth Nimbus specialty
    "family-medicine": ["Fam Med", "FAMILY PRACTICE", "FP", "Family Medicine"],
    "internal-medicine": ["IM", "Internal Med", "INTERNAL MEDICINE"],
    "pediatrics": ["PEDS", "Pediatrics"],
    "cardiology": ["CARDIO", "Cardiology"],
    "endocrinology": ["ENDO", "Endocrinology"],
    "emergency-medicine": ["ER", "EMERG MED", "Emergency Medicine"],
    "hospital-medicine": ["HOSPITALIST"],
    "nurse-practitioner": ["NP", "FNP"],
    "physician-assistant": ["PA-C"],
    "other": ["MISC", ""],
}

VISIT_TYPES = {  # code -> (truth class, weight)
    "OV": ("ambulatory", 50), "OVN": ("ambulatory", 10), "ER": ("emergency", 12),
    "IP": ("inpatient", 6), "OBS": ("observation", 4), "TEL": ("virtual", 10), "XX": (None, 1),
}

# ICD-9 -> list of plausible ICD-10 (first is the truth used by the generator)
ICD9 = {
    "250.00": ("Diabetes mellitus type 2 w/o complication", ["E11.9"]),
    "401.9": ("Essential hypertension", ["I10"]),
    "272.4": ("Hyperlipidemia NOS", ["E78.5"]),
    "493.90": ("Asthma unspecified", ["J45.909", "J45.20", "J45.40"]),
    "715.90": ("Osteoarthritis unspecified site", ["M19.90", "M17.9", "M16.9"]),
    "311": ("Depressive disorder NEC", ["F32.A", "F32.9"]),
    "530.81": ("Esophageal reflux", ["K21.9"]),
    "244.9": ("Hypothyroidism NOS", ["E03.9"]),
    "724.2": ("Lumbago", ["M54.50", "M54.59"]),
    "278.00": ("Obesity unspecified", ["E66.9"]),
    "427.31": ("Atrial fibrillation", ["I48.91"]),
    "496": ("Chronic airway obstruction", ["J44.9"]),
    "300.00": ("Anxiety state unspecified", ["F41.9"]),
}
ICD10 = {
    "E11.9": "Type 2 diabetes without complications", "I10": "Essential hypertension",
    "E78.5": "Hyperlipidemia, unspecified", "J45.909": "Asthma, unspecified, uncomplicated",
    "M54.50": "Low back pain, unspecified", "F32.A": "Depression, unspecified",
    "K21.9": "GERD without esophagitis", "E03.9": "Hypothyroidism, unspecified",
    "E66.9": "Obesity, unspecified", "I48.91": "Atrial fibrillation, unspecified",
    "J44.9": "COPD, unspecified", "F41.1": "Generalized anxiety disorder",
    "G43.909": "Migraine, unspecified", "E55.9": "Vitamin D deficiency, unspecified",
    "Z79.01": "Long term use of anticoagulants", "N39.0": "Urinary tract infection",
}
RETIRED_ICD10 = {"M54.5": ["M54.50", "M54.59"], "R51": ["R51.9"]}
LOCAL_DX = {"HZ001": ("Chronic pain syndrome", "G89.29"), "HZ014": ("Frailty", "R54"),
            "HZ099": ("Non-compliance w/ treatment", "Z91.19")}
FREE_TEXT_DX = ["bad back", "sugar", "high cholesterol", "nerves", "h/o fall"]

# formulary code -> (name, truth RxNorm or None, dose text variants, sig variants, anticoagulant/insulin flag)
FORMULARY = {
    "HFORM0001": ("LISINOPRIL 10MG TAB", "314076", ["10MG", "10 mg"], ["1 tab po daily", "1 TAB PO QD", "take one tablet by mouth once daily"], None),
    "HFORM0002": ("METFORMIN 500MG TAB", "861007", ["500MG", "500 mg"], ["1 tab po bid", "1 TAB PO BID WITH MEALS", "500mg po bid"], None),
    "HFORM0003": ("ATORVASTATIN 20MG TAB", "617312", ["20MG"], ["1 tab po qhs", "1 tab by mouth at bedtime"], None),
    "HFORM0004": ("WARFARIN 5MG TAB", "855332", ["5MG", "2.5 mg", "1/2 tab"], ["1 tab po daily", "1/2 tab po qhs", "ud per INR clinic"], "anticoagulant"),
    "HFORM0005": ("INSULIN GLARGINE 100 UNIT/ML", "285018", ["10 UNITS", "22 units"], ["10 units subq qhs", "22 UNITS SQ AT BEDTIME"], "insulin"),
    "HFORM0006": ("AMOXICILLIN 500MG CAP", "308191", ["500MG"], ["1 cap po tid x10d", "1 CAP PO TID X 10 DAYS"], None),
    "HFORM0007": ("ALBUTEROL HFA 90MCG INH", "745679", ["2 PUFFS"], ["2 puffs inh q4-6h prn sob", "2 PUFFS Q4H PRN WHEEZING"], None),
    "HFORM0008": ("LEVOTHYROXINE 50MCG TAB", "966222", ["50MCG", "50 mcg"], ["1 tab po qam", "1 tab po daily before breakfast"], None),
    "HFORM0009": ("OMEPRAZOLE 20MG CAP", "198053", ["20MG"], ["1 cap po daily ac", "1 CAP PO QD"], None),
    "HFORM0010": ("HYDROCODONE-APAP 5-325 TAB", "856999", ["1 TAB", "1-2 tabs"], ["1-2 tabs po q6h prn pain", "1 tab po q4-6h prn"], None),
    "HFORM0011": ("APIXABAN 5MG TAB", "1364445", ["5MG"], ["1 tab po bid", "5 mg by mouth twice daily"], "anticoagulant"),
    "HFORM0012": ("SERTRALINE 50MG TAB", "312940", ["50MG"], ["1 tab po daily", "1 TAB PO QD"], None),
    "HFORM0013": ("IBUPROFEN 600MG TAB", "197806", ["600MG"], ["1 tab po q8h prn pain with food", "600mg po tid prn"], None),
    "HFORM0014": ("PREDNISONE 10MG TAB", "312615", ["10MG", "40 mg"], ["taper as directed", "4 tabs po daily x5d"], None),
    "HFORM0015": ("MAGIC MOUTHWASH (COMPOUNDED)", None, ["10 ML"], ["swish and spit 10ml qid prn"], None),
    "HFORM0099": ("MISC MED SEE NOTE", None, [""], ["see note"], None),
}

# allergen text -> truth (system, code) or None if inherently uncodable
ALLERGENS = {
    "PCN": ("RxNorm", "7980"), "Penicillin": ("RxNorm", "7980"), "PENICILLINS": ("RxNorm", "7980"),
    "sulfa": ("SNOMED-CT", "387406002"), "Sulfa drugs": ("SNOMED-CT", "387406002"),
    "CODEINE": ("RxNorm", "2670"), "latex": ("SNOMED-CT", "111088007"), "LATEX": ("SNOMED-CT", "111088007"),
    "peanuts": ("SNOMED-CT", "256349002"), "Shellfish": ("SNOMED-CT", "227037002"),
    "IV contrast": ("SNOMED-CT", "293637006"), "ASA": ("RxNorm", "1191"), "Aspirin": ("RxNorm", "1191"),
    "Bee stings": None, "seasonal": None, "Grandma's casserole": None,
}
REACTIONS = {  # text -> SNOMED truth
    "HIVES": "247472004", "rash": "271807003", "anaphylaxis": "39579001", "SOB": "267036007",
    "N/V": "422587007", "swelling": "65124004", "itching": "418290006",
}

# local lab code -> (description, truth LOINC or None, source unit, kind, normal range, typical range)
LABS = {
    "GLU": ("GLUCOSE", "2345-7", "mg/dl", "num", (70, 99), (60, 300)),
    "K": ("POTASSIUM", "2823-3", "MEQ/L", "num", (3.5, 5.1), (2.8, 6.2)),
    "NA": ("SODIUM", "2951-2", "MEQ/L", "num", (136, 145), (125, 150)),
    "CREAT": ("CREATININE", "2160-0", "mg/dl", "num", (0.6, 1.2), (0.4, 4.0)),
    "HGBA1C": ("HEMOGLOBIN A1C", "4548-4", "%", "num", (4.0, 5.6), (4.5, 12.0)),
    "CHOL": ("CHOLESTEROL TOTAL", "2093-3", "mg/dl", "num", (0, 200), (120, 320)),
    "LDL": ("LDL CHOLESTEROL", "13457-7", "mg/dl", "num", (0, 100), (50, 220)),
    "HDL": ("HDL CHOLESTEROL", "2085-9", "mg/dl", "num", (40, 200), (25, 90)),
    "WBC": ("WHITE BLOOD COUNT", "6690-2", "K/uL", "num", (4.0, 11.0), (2.0, 20.0)),
    "HGB": ("HEMOGLOBIN", "718-7", "g/dl", "num", (12.0, 17.5), (7.0, 18.0)),
    "PLT": ("PLATELETS", "777-3", "K/uL", "num", (150, 400), (50, 600)),
    "TSH": ("TSH", "3016-3", "mIU/L", "num", (0.4, 4.0), (0.05, 15.0)),
    "INR": ("PROTIME INR", "6301-6", "", "num", (0.8, 1.2), (0.9, 4.5)),
    "VITD": ("VITAMIN D 25-OH", "1989-3", "ng/ml", "num", (30, 100), (8, 80)),
    "UAPROT": ("URINE PROTEIN QUAL", "20454-5", "", "coded", None, None),
    "STREP": ("RAPID STREP A", "78012-2", "", "coded", None, None),
    "XLAB7": ("SENDOUT MISC TEST", None, "", "text", None, None),
}

# Halcyon vaccine codes: CVX numbers for some rows, local codes for others
VACCINES = {
    "140": ("INFLUENZA PF", "140"), "141": ("INFLUENZA", "141"), "115": ("TDAP", "115"),
    "33": ("PNEUMOCOCCAL 23", "33"), "133": ("PCV13", "133"), "208": ("COVID-19 PFIZER", "208"),
    "187": ("ZOSTER RECOMB", "187"), "03": ("MMR", "03"), "62": ("HPV", "62"),
    "FLU-HD": ("FLU HIGH DOSE", "135"), "TDAP": ("TDAP", "115"), "PNEU23": ("PNEUMOVAX", "33"),
    "SHINGRIX": ("SHINGRIX", "187"), "PPD": ("TB SKIN TEST", None),  # PPD is not a vaccine
}

APPT_STATUS = {"S": "booked", "C": "fulfilled", "N": "noshow", "A": "arrived", "X": "cancelled", "B": None}

NOTE_TYPES = {"PN": ("Progress note", "11506-3"), "HP": ("History and physical", "34117-2"),
              "DS": ("Discharge summary", "18842-5"), "TEL": ("Telephone encounter", "34748-4")}

PAYERS = [("PY01", "BLUE PRAIRIE HEALTH"), ("PY02", "MEDICARE"), ("PY03", "STATE MEDICAID"),
          ("PY04", "ACME WORKERS COMP")]
PLANS = [("PL01", "PY01", "BLUE PRAIRIE PPO", "PPO"), ("PL02", "PY01", "BLUE PRAIRIE HMO", "HMO"),
         ("PL03", "PY02", "MEDICARE PART B", "MEDICARE"), ("PL04", "PY03", "MEDICAID FFS", "MEDICAID"),
         ("PL05", "PY04", "WORKERS COMP", "WC")]
REL_CODES = {"18": "self", "01": "spouse", "19": "child", "G8": "other", "": None}

# charge code -> (description, truth CPT/HCPCS, price dollars)
CHARGES = {
    "99212": ("OFFICE VISIT EST LVL2", "99212", 95), "99213": ("OFFICE VISIT EST LVL3", "99213", 135),
    "99214": ("OFFICE VISIT EST LVL4", "99214", 195), "99203": ("OFFICE VISIT NEW LVL3", "99203", 170),
    "99284": ("ED VISIT LVL4", "99284", 650), "99221": ("INITIAL HOSP CARE", "99221", 280),
    "80053": ("COMPREHENSIVE METABOLIC PANEL", "80053", 45), "83036": ("HEMOGLOBIN A1C", "83036", 30),
    "85025": ("CBC W DIFF", "85025", 28), "93000": ("ECG 12 LEAD", "93000", 60),
    "36415": ("VENIPUNCTURE", "36415", 12), "G0438": ("ANNUAL WELLNESS VISIT", "G0438", 175),
    "HC1001": ("FLU VACCINE ADMIN", "90471", 25), "HC1002": ("CHEST XRAY 2V", "71046", 110),
    "HC1003": ("KETOROLAC INJ", "J1885", 18), "HC9999": ("MISC SUPPLY", None, 5),
}

GENERIC_USERS = ["FRONTDESK1", "FRONTDESK2", "NURSE", "TEMP01", "REGISTRATION"]

FIRST_NAMES_F = ["Mary", "Linda", "Patricia", "Jennifer", "Maria", "Zoë", "Aisha", "Mei", "Sofia",
                 "Emily", "Grace", "Hannah", "Olivia", "Ana", "Fatima", "Priya", "Chloe", "Ruth", "Mary-Jo"]
FIRST_NAMES_M = ["James", "John", "Robert", "Michael", "José", "David", "Wei", "Ahmed", "Luis",
                 "Daniel", "Thomas", "Kevin", "Raj", "Samuel", "André", "Omar", "Henry", "Peter"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Garcia", "Nuñez", "O'Neil", "De La Cruz",
              "McDonald", "Nguyen", "Kim", "Patel", "Okafor", "Schmidt", "Rossi", "Kowalski",
              "Hernandez", "Lee", "Walker", "Young", "Martin", "Thompson", "Müller", "St. James"]
STREETS = ["MAIN ST", "OAK AVE", "RIVER RD", "2ND ST", "ELM ST", "LAKESHORE DR", "PRAIRIE LN", "MILL CT"]
CITIES = [("SPRINGFIELD", "IL", "627"), ("RIVERBEND", "IL", "618"), ("LAKESIDE", "CO", "805"),
          ("NORTHFIELD", "IL", "600")]
RACE_TEXT = {  # free text -> truth Nimbus race / ethnicity
    "WHITE": ("white", None), "Caucasian": ("white", None), "W": ("white", None),
    "BLACK": ("black-african-american", None), "African American": ("black-african-american", None),
    "ASIAN": ("asian", None), "Hispanic": (None, "hispanic-latino"), "Other": ("other", None),
    "DECLINED": ("asked-declined", None), "": ("unknown", None), "Native American": ("american-indian-alaska-native", None),
}
