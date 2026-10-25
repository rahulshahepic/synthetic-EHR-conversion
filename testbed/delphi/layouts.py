"""Fixed-width record layouts for a Delphi export.

This module is the single source of truth for the export format: the generator
renders records with it, the shipped ``LAYOUTS.DAT`` is generated from it, and
the round-trip tests parse with it. (Bridge has its own parser and reads
``LAYOUTS.DAT`` from the export; it never imports this module.)

Every file has one fixed record length (the widest of its record types);
shorter record types are space-padded to it. Every record starts with a
2-character record type (``RT``). Field types: ``T`` text (left-justified,
space-padded, truncated at the field width by the writing system), ``N``
numeric (right-justified, zero-padded; blank stays blank).
"""
from __future__ import annotations

# (file, record type) -> [(field, width, type, description)]
LAYOUTS: dict[tuple[str, str], list[tuple[str, int, str, str]]] = {
    ("REG", "A"): [
        ("RT", 2, "T", "record type: A = account"),
        ("ACCT", 7, "T", "registration account number"),
        ("NAME", 30, "T", "patient name: LAST,FIRST MIDDLE"),
        ("DOB", 6, "T", "date of birth, YYMMDD"),
        ("SEX", 1, "T", "sex: M, F or U"),
        ("SSN4", 4, "N", "last four digits of the social security number"),
        ("ADDR1", 30, "T", "address line 1"),
        ("ADDR2", 20, "T", "address line 2"),
        ("CITY", 16, "T", "city"),
        ("STATE", 2, "T", "state"),
        ("ZIP", 5, "N", "postal code"),
        ("PHONE", 14, "T", "home telephone, free format"),
        ("REGDATE", 6, "T", "registration date, YYMMDD"),
        ("DEATH", 6, "T", "date of death, YYMMDD, blank if living"),
        ("RACE", 10, "T", "race, free text"),
        ("PAYER", 3, "T", "primary payer code"),
        ("MEMBER", 12, "T", "insurance member number"),
        ("REL", 1, "T", "subscriber relationship: S, P, C, O"),
        ("ALGY", 40, "T", "allergies, comma separated free text, or NKA"),
    ],
    ("ENC", "V"): [
        ("RT", 2, "T", "record type: V = visit"),
        ("VISIT", 8, "T", "visit number"),
        ("ACCT", 7, "T", "registration account number"),
        ("UNIT", 3, "T", "unit: ER, MED, CLI, DAY"),
        ("CLASS", 3, "T", "visit class: IP, ER, OV, OBS, XX"),
        ("ADMITD", 6, "T", "admit date, YYMMDD"),
        ("ADMITT", 4, "N", "admit time, minutes since midnight"),
        ("DISD", 6, "T", "discharge date, YYMMDD"),
        ("DIST", 4, "N", "discharge time, minutes since midnight"),
        ("PROV", 6, "T", "attending provider code"),
        ("STATUS", 1, "T", "status: C complete, X cancelled, A arrived"),
        ("REASON", 20, "T", "reason for visit, free text"),
    ],
    ("DX", "P"): [
        ("RT", 2, "T", "record type: P = problem"),
        ("DXID", 8, "T", "problem number"),
        ("ACCT", 7, "T", "registration account number"),
        ("VISIT", 8, "T", "visit number, blank if not visit-specific"),
        ("CODE", 6, "T", "diagnosis shorthand code, blank if none"),
        ("TEXT", 50, "T", "diagnosis text as typed"),
        ("STATUS", 1, "T", "status: A active, I inactive, R resolved"),
        ("ONSET", 6, "T", "onset date, YYMMDD"),
        ("RESOLV", 6, "T", "resolved date, YYMMDD"),
    ],
    ("LAB", "A"): [
        ("RT", 2, "T", "record type: A = account"),
        ("ACCT", 7, "T", "laboratory account number"),
        ("NAME", 30, "T", "patient name: LAST,FIRST MIDDLE"),
        ("DOB", 6, "T", "date of birth, YYMMDD"),
        ("SEX", 1, "T", "sex: M, F or U"),
        ("SSN4", 4, "N", "last four digits of the social security number"),
        ("OPEN", 6, "T", "account opened date, YYMMDD"),
    ],
    ("LAB", "R"): [
        ("RT", 2, "T", "record type: R = result"),
        ("ACCT", 7, "T", "laboratory account number"),
        ("ACC", 9, "T", "accession number"),
        ("TEST", 5, "T", "test code (see LABDICT)"),
        ("RESULT", 10, "T", "result value with flag suffix, e.g. 12.4H"),
        ("YEAR", 2, "N", "collection year, two digits"),
        ("YDAY", 3, "N", "collection day of year (Julian)"),
        ("TIME", 4, "N", "collection time, minutes since midnight"),
    ],
    ("LABDICT", "T"): [
        ("RT", 2, "T", "record type: T = test dictionary"),
        ("TEST", 5, "T", "test code"),
        ("DESC", 24, "T", "test description"),
        ("UNIT", 8, "T", "reporting unit"),
        ("LOW", 6, "T", "reference range low, blank if none"),
        ("HIGH", 6, "T", "reference range high, blank if none"),
    ],
    ("DXDICT", "D"): [
        ("RT", 2, "T", "record type: D = shorthand dictionary"),
        ("CODE", 6, "T", "diagnosis shorthand code"),
        ("EXPAND", 50, "T", "shorthand expansion"),
    ],
    ("RAD", "A"): [
        ("RT", 2, "T", "record type: A = account"),
        ("ACCT", 7, "T", "radiology account number"),
        ("NAME", 30, "T", "patient name: LAST,FIRST MIDDLE"),
        ("DOB", 6, "T", "date of birth, YYMMDD"),
        ("SEX", 1, "T", "sex: M, F or U"),
        ("SSN4", 4, "N", "last four digits of the social security number"),
        ("OPEN", 6, "T", "account opened date, YYMMDD"),
    ],
    ("RAD", "X"): [
        ("RT", 2, "T", "record type: X = exam"),
        ("ACCT", 7, "T", "radiology account number"),
        ("EXAM", 8, "T", "exam number"),
        ("XCODE", 6, "T", "exam code"),
        ("DATE", 6, "T", "exam date, YYMMDD"),
        ("TIME", 4, "N", "exam time, minutes since midnight"),
        ("REPORT", 200, "T", "radiologist report text"),
    ],
    ("PHA", "A"): [
        ("RT", 2, "T", "record type: A = account"),
        ("ACCT", 7, "T", "pharmacy account number"),
        ("NAME", 30, "T", "patient name: LAST,FIRST MIDDLE"),
        ("DOB", 6, "T", "date of birth, YYMMDD"),
        ("SEX", 1, "T", "sex: M, F or U"),
        ("SSN4", 4, "N", "last four digits of the social security number"),
        ("OPEN", 6, "T", "account opened date, YYMMDD"),
    ],
    ("PHA", "M"): [
        ("RT", 2, "T", "record type: M = medication order"),
        ("ACCT", 7, "T", "pharmacy account number"),
        ("ORD", 8, "T", "order number"),
        ("NDC", 11, "N", "NDC, 11 digits, no dashes"),
        ("DRUG", 30, "T", "drug name as typed"),
        ("DOSE", 16, "T", "dose as typed, e.g. 500MG"),
        ("SIG", 44, "T", "directions as typed"),
        ("START", 6, "T", "start date, YYMMDD"),
        ("STOP", 6, "T", "stop date, YYMMDD"),
        ("STATUS", 1, "T", "status: A active, D discontinued, C completed"),
        ("PROV", 6, "T", "prescriber code"),
    ],
    ("NOTE", "N"): [
        ("RT", 2, "T", "record type: N = note header"),
        ("NOTE", 8, "T", "note number"),
        ("ACCT", 7, "T", "registration account number"),
        ("VISIT", 8, "T", "visit number"),
        ("TYPE", 3, "T", "note type: PN, OP, DS"),
        ("DATE", 6, "T", "note date, YYMMDD"),
        ("TIME", 4, "N", "note time, minutes since midnight"),
        ("PROV", 6, "T", "author provider code"),
        ("NLINES", 2, "N", "number of continuation records that follow"),
    ],
    ("NOTE", "C"): [
        ("RT", 2, "T", "record type: C = note continuation"),
        ("NOTE", 8, "T", "note number"),
        ("SEQ", 2, "N", "continuation sequence number"),
        ("TEXT", 72, "T", "note text, one line"),
    ],
    ("BILL", "B"): [
        ("RT", 2, "T", "record type: B = charge"),
        ("CHG", 8, "T", "charge number"),
        ("ACCT", 7, "T", "registration account number"),
        ("VISIT", 8, "T", "visit number"),
        ("CODE", 6, "T", "charge code (see CHGDICT)"),
        ("QTY", 3, "N", "quantity"),
        ("AMOUNT", 9, "N", "amount in cents"),
        ("POST", 6, "T", "posting date, YYMMDD"),
    ],
    ("CHGDICT", "C"): [
        ("RT", 2, "T", "record type: C = charge dictionary"),
        ("CODE", 6, "T", "charge code"),
        ("DESC", 30, "T", "charge description"),
        ("CPT", 6, "T", "CPT/HCPCS code, blank if none assigned"),
    ],
    ("APPT", "S"): [
        ("RT", 2, "T", "record type: S = appointment"),
        ("APPT", 8, "T", "appointment number"),
        ("ACCT", 7, "T", "registration account number"),
        ("DATE", 6, "T", "appointment date, YYMMDD"),
        ("TIME", 4, "N", "appointment time, minutes since midnight"),
        ("UNIT", 3, "T", "unit: ER, MED, CLI, DAY"),
        ("PROV", 6, "T", "provider code"),
        ("STATUS", 1, "T", "status: B booked, C complete, N no-show, A arrived, X cancelled, R rescheduled"),
        ("REASON", 16, "T", "reason, free text"),
    ],
    ("PROV", "D"): [
        ("RT", 2, "T", "record type: D = provider"),
        ("CODE", 6, "T", "provider code"),
        ("NAME", 30, "T", "provider name: LAST,FIRST M CREDENTIAL"),
        ("SPEC", 18, "T", "specialty, free text"),
        ("NPI", 10, "N", "NPI, blank if none on file"),
        ("ACT", 1, "T", "active: Y or N"),
        ("BILL", 1, "T", "billing provider: Y or N"),
    ],
    ("JOURNAL", "J"): [
        ("RT", 2, "T", "record type: J = journal entry"),
        ("SEQ", 6, "N", "journal sequence number"),
        ("OP", 1, "T", "operation: A add, C change, D delete"),
        ("FILE", 4, "T", "file the entry applies to"),
        ("KEY", 12, "T", "record key the entry applies to"),
        ("DATE", 6, "T", "entry date, YYMMDD"),
        ("TIME", 4, "N", "entry time, minutes since midnight"),
        ("FIELD", 6, "T", "changed field (change entries only)"),
        ("VALUE", 60, "T", "new value (change entries); summary otherwise"),
    ],
}

# file stem -> the extract filename in the export directory
FILES: dict[str, str] = {
    "REG": "REG.TXT", "ENC": "ENC.TXT", "DX": "DX.TXT", "LAB": "LAB.TXT",
    "LABDICT": "LABDICT.TXT", "DXDICT": "DXDICT.TXT", "RAD": "RAD.TXT",
    "PHA": "PHA.TXT", "NOTE": "NOTE.TXT", "BILL": "BILL.TXT",
    "CHGDICT": "CHGDICT.TXT", "APPT": "APPT.TXT", "PROV": "PROV.TXT",
    "JOURNAL": "JOURNAL.TXT",
}


def _starts(fields: list[tuple[str, int, str, str]]) -> list[tuple[str, int, int, str, str]]:
    """[(field, start [0-based], width, type, description)] for one layout."""
    out, pos = [], 0
    for name, width, typ, desc in fields:
        out.append((name, pos, width, typ, desc))
        pos += width
    return out


SPANS: dict[tuple[str, str], list[tuple[str, int, int, str, str]]] = {
    key: _starts(fields) for key, fields in LAYOUTS.items()
}


def record_length(file: str) -> int:
    """The fixed record length of one extract file: the widest of its record types."""
    return max(sum(w for _, w, _, _ in fields) for (f, _), fields in LAYOUTS.items() if f == file)


def format_record(file: str, rt: str, values: dict[str, str]) -> str:
    """Render one record at the file's fixed length. Text fields truncate at
    their width (that is what the writing system does); numeric fields
    zero-pad; blanks stay blank."""
    parts = []
    for name, width, typ, _ in LAYOUTS[(file, rt)]:
        v = str(values.get(name, ""))
        v = v[:width]
        parts.append(v.rjust(width, "0") if typ == "N" and v.strip() else v.ljust(width))
    return "".join(parts).ljust(record_length(file))


def parse_record(file: str, line: str) -> dict[str, str]:
    """Parse one fixed-width line with its record type's layout. Values are stripped."""
    rt = line[:2].strip()
    return {name: line[start:start + width].strip() for name, start, width, _, _ in SPANS[(file, rt)]}


LAYOUT_VERSION = "5.0"


def layouts_dat() -> str:
    """The machine-readable layout file shipped in every export (LAYOUTS.DAT)."""
    lines = [f"# DELPHI EXTRACT LAYOUTS - VERSION {LAYOUT_VERSION}", "FILE|RT|FIELD|START|LEN|TYPE|DESC"]
    for (file, rt), spans in sorted(SPANS.items()):
        for name, start, width, typ, desc in spans:
            lines.append(f"{file}|{rt}|{name}|{start + 1}|{width}|{typ}|{desc}")
    return "\n".join(lines) + "\n"
