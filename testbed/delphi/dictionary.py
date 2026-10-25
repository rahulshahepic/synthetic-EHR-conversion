"""The vendor data dictionary that ships with every Delphi export (DATADICT.TXT).

This is an in-universe document: it is *mostly* right, and wrong in specific,
recorded ways. The discrepancies are deliberate and are ledgered in
``answer_key/estate_discrepancies.json`` (see DISCREPANCIES below) so a future
interview/onboarding process can be graded against them. Nothing in the
dictionary text itself hints at which entries are wrong.
"""

DATADICT_TEXT = """\
DELPHI HEALTH SYSTEMS
PATIENT CARE SYSTEM - DATA DICTIONARY
VERSION 4.1 - MARCH 2019

THIS DICTIONARY DESCRIBES THE NIGHTLY EXTRACT FILES PRODUCED BY THE DELPHI
PATIENT CARE SYSTEM AT ST. AMBROSE MEMORIAL. FIELD POSITIONS AND LENGTHS ARE
GOVERNED BY THE LAYOUT FILE (LAYOUTS.DAT) DELIVERED WITH EACH EXTRACT.

GENERAL CONVENTIONS

ALL FILES ARE FIXED LENGTH TEXT. EVERY RECORD BEGINS WITH A TWO CHARACTER
RECORD TYPE. TEXT IS STORED IN UPPERCASE.

DATES ARE STORED AS SIX DIGITS. IN THE REGISTRATION FILE THE ORDER IS
MMDDYY (MONTH, DAY, YEAR). TWO DIGIT YEARS ARE INTERPRETED USING A PIVOT
YEAR OF 50: YEARS 00 THROUGH 49 ARE 20XX, YEARS 50 THROUGH 99 ARE 19XX.

TIMES ARE STORED AS MINUTES SINCE MIDNIGHT (0000 TO 1439).

== FILE: REG (REGISTRATION ACCOUNTS), RECORD TYPE A ==

ACCT      REGISTRATION ACCOUNT NUMBER. ONE ACCOUNT PER PATIENT.
NAME      PATIENT NAME: LAST, FIRST MIDDLE. FULL NAME AS PROVIDED.
DOB       DATE OF BIRTH, MMDDYY (SEE GENERAL CONVENTIONS).
SEX       SEX: M, F OR U.
SSN4      LAST FOUR DIGITS OF THE SOCIAL SECURITY NUMBER.
ADDR1     ADDRESS LINE 1.
ADDR2     ADDRESS LINE 2.
CITY      CITY.
STATE     STATE.
ZIP       POSTAL CODE.
PHONE     HOME TELEPHONE, FREE FORMAT.
FAX       FAX NUMBER, FREE FORMAT.
REGDATE   DATE THE ACCOUNT WAS OPENED, YYMMDD.
DEATH     DATE OF DEATH, YYMMDD, BLANK IF LIVING.
RACE      RACE, FREE TEXT.
PAYER     PRIMARY PAYER CODE.
MEMBER    INSURANCE MEMBER NUMBER.
REL       SUBSCRIBER RELATIONSHIP: S SELF, P SPOUSE, C CHILD, O OTHER.

== FILE: ENC (ENCOUNTERS), RECORD TYPE V ==

VISIT     VISIT NUMBER.
ACCT      REGISTRATION ACCOUNT NUMBER.
UNIT      UNIT: ER, MED, CLI, DAY.
CLASS     VISIT CLASS: IP, ER, OV, OBS, XX.
ADMITD    ADMIT DATE, YYMMDD.
ADMITT    ADMIT TIME, MINUTES SINCE MIDNIGHT.
DISD      DISCHARGE DATE, YYMMDD.
DIST      DISCHARGE TIME, MINUTES SINCE MIDNIGHT.
PROV      ATTENDING PROVIDER CODE.
STATUS    STATUS: C COMPLETE, X CANCELLED, A ARRIVED.
REASON    REASON FOR VISIT, FREE TEXT.

== FILE: DX (PROBLEM LIST), RECORD TYPE P ==

DXID      PROBLEM NUMBER.
ACCT      REGISTRATION ACCOUNT NUMBER.
VISIT     VISIT NUMBER, BLANK IF NOT VISIT SPECIFIC.
CODE      DIAGNOSIS SHORTHAND CODE (SEE DXDICT.TXT), BLANK IF NONE.
TEXT      DIAGNOSIS TEXT AS TYPED.
STATUS    STATUS: A ACTIVE, I INACTIVE, R RESOLVED, BLANK.
ONSET     ONSET DATE, YYMMDD.
RESOLV    RESOLVED DATE, YYMMDD.

== FILE: LAB (LABORATORY), RECORD TYPES A AND R ==

RECORD TYPE A IS THE LABORATORY ACCOUNT: ACCT, NAME, DOB, SEX, SSN4 AND
OPEN (DATE OPENED, YYMMDD). THE LABORATORY ACCOUNT NUMBER IS ASSIGNED BY
THE LABORATORY AND IS USED ON ALL RESULT RECORDS.

RECORD TYPE R IS A RESULT:

ACCT      LABORATORY ACCOUNT NUMBER.
ACC       ACCESSION NUMBER.
TEST      TEST CODE (SEE LABDICT.TXT).
RESULT    RESULT VALUE. AN ABNORMAL RESULT CARRIES ITS FLAG AS A SUFFIX,
          FOR EXAMPLE 12.4H (HIGH) OR 3.2L (LOW).
YEAR      COLLECTION YEAR, TWO DIGITS.
TIME      COLLECTION TIME, MINUTES SINCE MIDNIGHT.

REFERENCE RANGES AND REPORTING UNITS FOR EACH TEST ARE IN LABDICT.TXT.
POTASSIUM (TEST POT) IS REPORTED IN MG/DL.

== FILE: RAD (RADIOLOGY), RECORD TYPES A AND X ==

RECORD TYPE A IS THE RADIOLOGY ACCOUNT: ACCT, NAME, DOB, SEX, SSN4, OPEN.
RECORD TYPE X IS AN EXAM: ACCT, EXAM (EXAM NUMBER), XCODE (EXAM CODE),
DATE AND TIME OF THE EXAM, AND REPORT (THE RADIOLOGIST'S REPORT TEXT).

== FILE: PHA (PHARMACY), RECORD TYPES A AND M ==

RECORD TYPE A IS THE PHARMACY ACCOUNT: ACCT, NAME, DOB, SEX, SSN4, OPEN.
RECORD TYPE M IS A MEDICATION ORDER: ACCT, ORD (ORDER NUMBER), NDC
(ELEVEN DIGIT NATIONAL DRUG CODE), DRUG (NAME AS TYPED), DOSE (AS TYPED),
SIG (DIRECTIONS AS TYPED), START AND STOP DATES (YYMMDD), STATUS
(A ACTIVE, D DISCONTINUED, C COMPLETED) AND PROV (PRESCRIBER CODE).

== FILE: NOTE (CLINICAL NOTES), RECORD TYPES N AND C ==

RECORD TYPE N IS A NOTE HEADER: NOTE (NOTE NUMBER), ACCT, VISIT, TYPE
(PN PROGRESS, OP OPERATIVE, DS DISCHARGE), DATE, TIME, PROV (AUTHOR) AND
NLINES (NUMBER OF CONTINUATION RECORDS). RECORD TYPE C IS A CONTINUATION
LINE: NOTE, SEQ AND TEXT (72 CHARACTERS).

== FILE: BILL (CHARGES), RECORD TYPE B ==

CHG       CHARGE NUMBER.
ACCT      REGISTRATION ACCOUNT NUMBER.
VISIT     VISIT NUMBER.
CODE      CHARGE CODE (SEE CHGDICT.TXT).
QTY       QUANTITY.
AMOUNT    AMOUNT IN CENTS.
POST      POSTING DATE, YYMMDD.

== FILE: APPT (APPOINTMENTS), RECORD TYPE S ==

APPT      APPOINTMENT NUMBER.
ACCT      REGISTRATION ACCOUNT NUMBER.
DATE      APPOINTMENT DATE, YYMMDD.
TIME      APPOINTMENT TIME, MINUTES SINCE MIDNIGHT.
UNIT      UNIT: ER, MED, CLI, DAY.
PROV      PROVIDER CODE.
STATUS    STATUS: B BOOKED, C COMPLETE, N NO-SHOW, A ARRIVED, X CANCELLED.
REASON    REASON, FREE TEXT.

== FILE: PROV (PROVIDERS), RECORD TYPE D ==

CODE      PROVIDER CODE.
NAME      PROVIDER NAME: LAST, FIRST M CREDENTIAL.
SPEC      SPECIALTY, FREE TEXT.
NPI       NATIONAL PROVIDER IDENTIFIER, BLANK IF NONE ON FILE.
ACT       ACTIVE: Y OR N.
BILL      BILLING PROVIDER: Y OR N.

== FILE: JOURNAL (TRANSACTION JOURNAL), RECORD TYPE J ==

THE JOURNAL IS THE SYSTEM AUDIT LOG. ONE ENTRY IS WRITTEN FOR EVERY ADD,
CHANGE OR DELETE IN THE FILES ABOVE (OP: A, C OR D), WITH THE ENTRY DATE
AND TIME, THE FIELD CHANGED (CHANGE ENTRIES) AND THE NEW VALUE. THE
JOURNAL IS RETAINED FOR AUDIT PURPOSES.

END OF DICTIONARY - DELPHI HEALTH SYSTEMS, TECHNICAL PUBLICATIONS
"""

# The truth ledger: every deliberate discrepancy between the estate's
# documents and what the generator actually produces. Written verbatim to
# answer_key/estate_discrepancies.json by the generator.
DISCREPANCIES: list[dict[str, str]] = [
    {
        "id": "dict_version_skew",
        "artifact": "DATADICT.TXT",
        "claim": "The data dictionary is version 4.1, dated March 2019.",
        "truth": "The shipped layouts (LAYOUTS.DAT) are version 5.0. The dictionary predates the "
                 "current layouts; several of its entries describe the version 4 system.",
        "check": "Compare the version line of DATADICT.TXT with the version comment in LAYOUTS.DAT.",
    },
    {
        "id": "dict_dob_format",
        "artifact": "DATADICT.TXT",
        "claim": "Registration dates (DOB) are stored MMDDYY (month, day, year).",
        "truth": "All six-digit dates in every file, registration included, are YYMMDD.",
        "check": "REGDATE values in REG.TXT frequently exceed 12 in the first two positions only "
                 "when read as YY; read as MMDDYY most registration dates are invalid.",
    },
    {
        "id": "dict_pivot_year",
        "artifact": "DATADICT.TXT",
        "claim": "Two-digit years are interpreted with a pivot year of 50 (00-49 are 20xx).",
        "truth": "The generator writes years with a pivot year of 30 (00-29 are 20xx, 30-99 are 19xx).",
        "check": "Persons born 1930-1949 exist in the population; under the dictionary's pivot their "
                 "birth years convert to 2030-2049, after their own registration and visit dates.",
    },
    {
        "id": "dict_potassium_unit",
        "artifact": "DATADICT.TXT",
        "claim": "Potassium (test POT) is reported in MG/DL.",
        "truth": "Potassium results are in MEQ/L, as LABDICT.TXT states and as the value range "
                 "(roughly 2.8-6.2 against a 3.5-5.1 reference range) requires.",
        "check": "Read the POT row of LABDICT.TXT and the RESULT values for POT in LAB.TXT.",
    },
    {
        "id": "dict_stale_field_fax",
        "artifact": "DATADICT.TXT",
        "claim": "The registration record contains a FAX field (fax number, free format).",
        "truth": "There is no FAX field in the current layouts; it was removed in layout version 5. "
                 "The registration record's fields are exactly those in LAYOUTS.DAT.",
        "check": "Search LAYOUTS.DAT for a REG field named FAX: none exists.",
    },
    {
        "id": "dict_undocumented_yday",
        "artifact": "DATADICT.TXT",
        "claim": "The lab result record is documented with YEAR and TIME collection fields only.",
        "truth": "The result record also carries YDAY, the Julian day of year, and the collection "
                 "date cannot be reconstructed without it: lab dates are Julian (YEAR + YDAY), "
                 "not calendar dates.",
        "check": "Read the LAB/R layout in LAYOUTS.DAT; YDAY is present in the layout and in every "
                 "result record, and is absent from the dictionary's field list.",
    },
    {
        "id": "dict_undocumented_allergy_field",
        "artifact": "DATADICT.TXT",
        "claim": "The registration record's documented fields end at REL; no allergy field is listed.",
        "truth": "The registration record carries ALGY, a 40-character free-text allergy field "
                 "('NKA' or comma-separated allergen text). It is the export's only allergy source.",
        "check": "Read the REG/A layout in LAYOUTS.DAT and the tail of any REG.TXT record.",
    },
    {
        "id": "dict_appt_status_incomplete",
        "artifact": "DATADICT.TXT",
        "claim": "Appointment status is one of B, C, N, A, X.",
        "truth": "Status R (rescheduled) also occurs in APPT.TXT and is not documented.",
        "check": "Collect the distinct STATUS values in APPT.TXT; R appears and is not in the "
                 "dictionary's list.",
    },
    {
        "id": "dict_registration_account_claim",
        "artifact": "DATADICT.TXT",
        "claim": "The registration account number is 'one account per patient'.",
        "truth": "Registration itself sometimes opens a second account for the same patient "
                 "(duplicate registration), and each department assigns further account numbers; "
                 "one patient normally holds several accounts across the export.",
        "check": "The answer key's persons.json maps most persons to two or more account numbers, "
                 "including, for some, two R-prefixed registration accounts.",
    },
]
