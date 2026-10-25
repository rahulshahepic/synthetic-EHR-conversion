"""Delphi local vocabularies with the *true* meaning of each code.

The truth columns (LOINC/RxNorm/ICD-10/CPT) are what a perfect conversion would produce.
They exist so tests can score Bridge; Bridge itself must build its own crosswalks.
All codes, NDCs and descriptions are invented for this fixture and labeled synthetic.
"""

HOSPITAL = ("STAMB", "St. Ambrose Memorial", "America/Chicago")

# department -> (account prefix, display name). Each department assigns its
# own account numbers; there is no master patient index.
ACCOUNT_DEPTS = {
    "REG": ("R", "REGISTRATION"),
    "LAB": ("L", "LABORATORY"),
    "RAD": ("X", "RADIOLOGY"),
    "PHA": ("P", "PHARMACY"),
}

# clinical units that host encounters (also staged as departments/locations)
UNITS = [
    ("ER", "EMERGENCY DEPT", "ed"),
    ("MED", "MED/SURG 4E", "inpatient"),
    ("CLI", "AMBULATORY CLINIC", "clinic"),
    ("DAY", "DAY SURGERY", "clinic"),
]

# visit class code -> truth Nimbus encounter class (None = uncoded in Delphi)
VISIT_CLASSES = {"IP": "inpatient", "ER": "emergency", "OV": "ambulatory", "OBS": "observation", "XX": None}
# sampling weights per class
VISIT_CLASS_WEIGHTS = {"IP": 8, "ER": 14, "OV": 62, "OBS": 10, "XX": 2}
# truth class -> unit a visit of that class is hosted in
CLASS_UNIT = {"inpatient": "MED", "emergency": "ER", "ambulatory": "CLI", "observation": "DAY", None: "CLI"}

# Diagnosis shorthand -> (expansion as documented in DXDICT, truth ICD-10).
# Clinicians also type diagnoses as free text with no code at all.
DX_SHORTHAND = {
    "DM2": ("DIABETES MELLITUS TYPE 2", "E11.9"),
    "HTN": ("HYPERTENSION", "I10"),
    "CHF": ("CONGESTIVE HEART FAILURE", "I50.9"),
    "COPD": ("CHRONIC OBSTRUCTIVE PULMONARY DISEASE", "J44.9"),
    "CKD3": ("CHRONIC KIDNEY DISEASE STAGE 3", "N18.30"),
    "OA": ("OSTEOARTHRITIS", "M19.90"),
    "GERD": ("GASTROESOPHAGEAL REFLUX DISEASE", "K21.9"),
    "ANX": ("ANXIETY", "F41.9"),
    "DEP": ("DEPRESSION", "F32.A"),
    "ASTH": ("ASTHMA", "J45.909"),
    "UTI": ("URINARY TRACT INFECTION", "N39.0"),
    "PNA": ("PNEUMONIA", "J18.9"),
    "THYR": ("HYPOTHYROIDISM", "E03.9"),
    "LBP": ("LOW BACK PAIN", "M54.50"),
    "AFIB": ("ATRIAL FIBRILLATION", "I48.91"),
    "HLIP": ("HYPERLIPIDEMIA", "E78.5"),
}
FREE_TEXT_DX = ["LOW BACK PAIN", "CHEST PAIN", "SHORT OF BREATH", "BELLY PAIN", "DIZZY SPELLS",
                "CANT SLEEP", "SUGAR PROBLEM", "BAD KNEE"]
# chronic condition pool (shorthand codes) sampled per person, by age band
CHRONIC_POOL = ["DM2", "HTN", "CHF", "COPD", "CKD3", "OA", "GERD", "ANX", "DEP", "ASTH",
                "THYR", "AFIB", "HLIP"]
CHRONIC_MEDS = {  # shorthand dx -> formulary NDCs usually prescribed for it
    "DM2": ["00999000201", "00999000501"], "HTN": ["00999000101"], "HLIP": ["00999000301"],
    "AFIB": ["00999000401", "00999001101"], "THYR": ["00999000801"], "GERD": ["00999000901"],
    "DEP": ["00999001201"], "ASTH": ["00999000701"],
}

# NDC (11 digits, synthetic) -> (drug name, truth RxNorm or None, dose variants, sig variants, flag)
FORMULARY = {
    "00999000101": ("LISINOPRIL 10MG TAB", "314076", ["10MG", "10 mg"], ["1 TAB PO DAILY", "1 TAB PO QD"], None),
    "00999000201": ("METFORMIN 500MG TAB", "861007", ["500MG", "500 mg"], ["1 TAB PO BID", "1 TAB PO BID WITH MEALS"], None),
    "00999000301": ("ATORVASTATIN 20MG TAB", "617312", ["20MG"], ["1 TAB PO QHS"], None),
    "00999000401": ("WARFARIN 5MG TAB", "855332", ["5MG", "2.5 mg", "1/2 tab"], ["1 TAB PO DAILY", "1/2 TAB PO QHS"], "anticoagulant"),
    "00999000501": ("INSULIN GLARGINE 100 UNIT/ML", "285018", ["10 UNITS", "22 units"], ["10 UNITS SUBQ QHS", "22 UNITS SQ AT BEDTIME"], "insulin"),
    "00999000601": ("AMOXICILLIN 500MG CAP", "308191", ["500MG"], ["1 CAP PO TID X10D"], None),
    "00999000701": ("ALBUTEROL HFA 90MCG INH", "745679", ["2 PUFFS"], ["2 PUFFS INH Q4-6H PRN SOB"], None),
    "00999000801": ("LEVOTHYROXINE 50MCG TAB", "966222", ["50MCG", "50 mcg"], ["1 TAB PO QAM"], None),
    "00999000901": ("OMEPRAZOLE 20MG CAP", "198053", ["20MG"], ["1 CAP PO DAILY AC"], None),
    "00999001001": ("HYDROCODONE-APAP 5-325 TAB", "856999", ["1 TAB", "1-2 tabs"], ["1-2 TABS PO Q6H PRN PAIN"], None),
    "00999001101": ("APIXABAN 5MG TAB", "1364445", ["5MG"], ["1 TAB PO BID"], "anticoagulant"),
    "00999001201": ("SERTRALINE 50MG TAB", "312940", ["50MG"], ["1 TAB PO DAILY"], None),
    "00999001301": ("IBUPROFEN 600MG TAB", "197806", ["600MG"], ["1 TAB PO Q8H PRN PAIN WITH FOOD"], None),
    "00999001501": ("MAGIC MOUTHWASH COMPOUNDED", None, ["10 ML"], ["SWISH AND SPIT 10ML QID PRN"], None),
    "00999009901": ("MISC MED SEE NOTE", None, [""], ["SEE NOTE"], None),
}
ACUTE_NDCS = ["00999000601", "00999001001", "00999001301", "00999001501", "00999009901"]

# local lab code -> (description, truth LOINC or None, unit, (ref low, ref high) as dictionary
# strings ("" = none), typical numeric range, kind)
LABS = {
    "GLU": ("GLUCOSE", "2345-7", "mg/dl", ("70", "99"), (60, 300), "num"),
    "POT": ("POTASSIUM", "2823-3", "MEQ/L", ("3.5", "5.1"), (2.8, 6.2), "num"),
    "SOD": ("SODIUM", "2951-2", "MEQ/L", ("136", "145"), (125, 150), "num"),
    "CREA": ("CREATININE", "2160-0", "mg/dl", ("0.6", "1.2"), (0.4, 4.0), "num"),
    "A1C": ("HEMOGLOBIN A1C", "4548-4", "%", ("4.0", "5.6"), (4.5, 12.0), "num"),
    "CHOL": ("CHOLESTEROL TOTAL", "2093-3", "mg/dl", ("", "200"), (120, 320), "num"),
    "WBC": ("WHITE BLOOD COUNT", "6690-2", "K/UL", ("4.0", "11.0"), (2.0, 20.0), "num"),
    "HGB": ("HEMOGLOBIN", "718-7", "g/dl", ("12.0", "17.5"), (7.0, 18.0), "num"),
    "PLT": ("PLATELETS", "777-3", "K/UL", ("150", "400"), (50, 600), "num"),
    "TSH": ("TSH", "3016-3", "MIU/L", ("0.4", "4.0"), (0.05, 15.0), "num"),
    "UAP": ("URINE PROTEIN QUAL", "20454-5", "", ("", ""), None, "coded"),
    "MISC": ("SENDOUT MISC TEST", None, "", ("", ""), None, "text"),
}

# allergy token -> truth (system, code) or None if inherently uncodable
ALLERGENS = {
    "PENICILLIN": ("RxNorm", "7980"), "PCN": ("RxNorm", "7980"), "SULFA": ("SNOMED-CT", "387406002"),
    "CODEINE": ("RxNorm", "2670"), "LATEX": ("SNOMED-CT", "111088007"),
    "PEANUTS": ("SNOMED-CT", "256349002"), "SHELLFISH": ("SNOMED-CT", "227037002"),
    "IV CONTRAST": ("SNOMED-CT", "293637006"), "ASPIRIN": ("RxNorm", "1191"),
    "DUST": None, "POLLEN": None, "MOLD": None,
}

SPECIALTY_TEXT = {  # free text variants -> truth Nimbus specialty (mirrors Halcyon's map)
    "family-medicine": ["FAM MED", "FAMILY PRACTICE", "FP"],
    "internal-medicine": ["IM", "INTERNAL MED"],
    "pediatrics": ["PEDS", "PEDIATRICS"],
    "cardiology": ["CARDIO", "CARDIOLOGY"],
    "endocrinology": ["ENDO"],
    "emergency-medicine": ["ER", "EMERG MED"],
    "hospital-medicine": ["HOSPITALIST"],
    "nurse-practitioner": ["NP", "FNP"],
    "other": ["MISC", ""],
}

PAYERS = {"BPP": "BLUE PRAIRIE HEALTH", "MCR": "MEDICARE", "MCD": "STATE MEDICAID", "WCP": "ACME WORKERS COMP"}
PLANS = {"BPP": ("BLUE PRAIRIE PPO", "PPO"), "MCR": ("MEDICARE PART B", "MEDICARE"),
         "MCD": ("MEDICAID FFS", "MEDICAID"), "WCP": ("WORKERS COMP", "WC")}
REL_CODES = {"S": "self", "P": "spouse", "C": "child", "O": "other"}

# charge code -> (description, truth CPT/HCPCS or None, price dollars)
CHARGES = {
    "OFV2": ("OFFICE VISIT EST LVL2", "99212", 95), "OFV3": ("OFFICE VISIT EST LVL3", "99213", 135),
    "OFV4": ("OFFICE VISIT EST LVL4", "99214", 195), "EDV4": ("ED VISIT LVL4", "99284", 650),
    "HOSP": ("INITIAL HOSP CARE", "99221", 280), "CMP": ("COMPREHENSIVE METABOLIC PANEL", "80053", 45),
    "A1CL": ("HEMOGLOBIN A1C", "83036", 30), "CBC": ("CBC W DIFF", "85025", 28),
    "ECG": ("ECG 12 LEAD", "93000", 60), "DRAW": ("VENIPUNCTURE", "36415", 12),
    "SUPP": ("MISC SUPPLY", None, 5),
}
VISIT_CHARGES = {"emergency": ["EDV4", "ECG"], "inpatient": ["HOSP", "CMP", "CBC"],
                 "observation": ["HOSP", "CMP"], "ambulatory": ["OFV2", "OFV3", "OFV4", "A1CL", "DRAW"]}

EXAM_CODES = {"CXR2V": "CHEST XRAY 2 VIEWS", "CTHEAD": "CT HEAD WO CONTRAST", "ABD1V": "ABDOMEN XRAY 1 VIEW",
              "KNEE3": "KNEE XRAY 3 VIEWS", "SPINE2": "LUMBAR SPINE 2 VIEWS"}
NOTE_TYPES = ["PN", "OP", "DS"]

FIRST_NAMES_F = ["Mary", "Linda", "Patricia", "Jennifer", "Maria", "Zoë", "Aisha", "Mei", "Sofia",
                 "Emily", "Grace", "Hannah", "Olivia", "Ana", "Fatima", "Priya", "Chloe", "Ruth", "Mary-Jo",
                 "Alexandria", "Evangeline"]
FIRST_NAMES_M = ["James", "John", "Robert", "Michael", "José", "David", "Wei", "Ahmed", "Luis",
                 "Daniel", "Thomas", "Kevin", "Raj", "Samuel", "André", "Omar", "Henry", "Peter",
                 "Christopher", "Bartholomew", "Maximilian"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Garcia", "Nuñez", "O'Neil", "De La Cruz",
              "McDonald", "Nguyen", "Kim", "Patel", "Okafor", "Schmidt", "Rossi", "Kowalski",
              "Hernandez", "Lee", "Walker", "Young", "Martin", "Thompson", "Müller", "St. James",
              "Alexandropoulos", "Vandergrift", "Featherstonehaugh", "Wojciechowski"]
STREETS = ["MAIN ST", "OAK AVE", "RIVER RD", "2ND ST", "ELM ST", "LAKESHORE DR", "PRAIRIE LN", "MILL CT"]
CITIES = [("SPRINGFIELD", "IL", "627"), ("SHERMAN", "IL", "626"), ("CHATHAM", "IL", "626")]
RACE_TEXT = ["WHITE", "Caucasian", "W", "BLACK", "African American", "ASIAN", "Hispanic", "Other",
             "DECLINED", "", "Native American"]
REASONS = ["F/U", "ANNUAL", "COUGH", "CHEST PAIN", "MED REFILL", "FALL", "CHECKUP", ""]
NOTE_LINES = [
    "PT SEEN IN CLINIC TODAY. REPORTS FEELING SOMEWHAT BETTER.",
    "EXAM UNREMARKABLE. VITALS STABLE. NO NEW COMPLAINTS.",
    "ASSESSMENT UNCHANGED. CONTINUE CURRENT MEDS AND FOLLOW UP.",
    "LABS REVIEWED WITH PT. PLAN DISCUSSED. QUESTIONS ANSWERED.",
    "PT TOLERATING TREATMENT WELL. WILL RECHECK AT NEXT VISIT.",
    "HISTORY AS PREVIOUSLY DOCUMENTED. NO INTERVAL EVENTS.",
]
REPORT_LINES = [
    "NO ACUTE FINDINGS. HEART AND LUNGS APPEAR NORMAL.",
    "FINDINGS ARE UNREMARKABLE. NO FRACTURE OR DISLOCATION SEEN.",
    "MILD DEGENERATIVE CHANGES. OTHERWISE NORMAL STUDY.",
    "NO EVIDENCE OF ACUTE DISEASE. CLINICAL CORRELATION ADVISED.",
]
