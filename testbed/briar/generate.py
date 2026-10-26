"""Fixture authoring only. Conversion code must not import this module.

Truth is written separately for post-run scoring. All people and codes are synthetic.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA = {
    "REG": [("RT", 2), ("SITE", 1), ("CHART", 6), ("NAME", 30), ("DOB", 8), ("SEX", 1), ("NKA", 1), ("ALLERGY", 40)],
    "VIS": [("RT", 2), ("SITE", 1), ("ID", 8), ("CHART", 6), ("DAY", 8), ("TIME", 4), ("STATUS", 1)],
    "LAB": [("RT", 2), ("SITE", 1), ("ID", 8), ("CHART", 6), ("TEST", 8), ("REV", 2), ("DAY", 8), ("TIME", 4), ("RESULT", 16), ("UNIT", 10), ("STATUS", 1)],
    "MED": [("RT", 2), ("SITE", 1), ("ID", 8), ("CHART", 6), ("DRUG", 8), ("NAME", 35), ("DAY", 8), ("STATUS", 1), ("SIG", 60)],
    "DX": [("RT", 2), ("SITE", 1), ("ID", 8), ("CHART", 6), ("CODE", 8), ("TEXT", 60), ("STATUS", 1)],
    "NOTE": [("RT", 2), ("SITE", 1), ("ID", 8), ("CHART", 6), ("SEQ", 2), ("DAY", 8), ("TIME", 4), ("TEXT", 72)],
    "APPT": [("RT", 2), ("SITE", 1), ("ID", 8), ("CHART", 6), ("DAY", 8), ("TIME", 4), ("STATUS", 1)],
    "BILL": [("RT", 2), ("SITE", 1), ("ID", 8), ("CHART", 6), ("VISIT", 8), ("DAY", 8), ("AMOUNT", 12), ("CODE", 8)],
    "JRN": [("RT", 2), ("SITE", 1), ("SEQ", 6), ("TABLE", 8), ("ID", 8), ("ACTION", 1)],
}


DOCUMENT = """BRIAR COMMUNITY EHR - EXPORT DATA DICTIONARY 2.3 (2018)
All data and codes in this estate are invented for testing.
Most field names mean what they say. LAYOUTS.DAT is the delivery layout.
REG: one record per patient. CHART is the enterprise patient identifier.
NAME is LAST,FIRST. DOB is YYMMDD, window 1950-2049. SEX M/F/U.
NKA Y means no known allergies; ALLERGY contains substance and reaction text.
VIS: outpatient ambulatory visits only; DAY YYYYMMDD, TIME HHMM local; STATUS F finished or I in progress.
Every site uses America/Chicago. A time of 2400 means the next midnight.
LAB: ID is accession; TEST local dictionary; REV revision number.
Only latest revision of each SITE+ID+TEST is current. Suffix H/L flags abnormality.
LAB timestamps are local HHMM. STATUS F final, P preliminary, C corrected.
RESULT is numeric, UNIT overrides the test dictionary.
MED: A active, S stopped, H historical (do not import). SIG is clinician-entered text.
DX: CODE is local shorthand; TEXT original wording, A active/R resolved.
NOTE: ID document number, SEQ continuation order, one 72-column segment per row.
APPT: B booked, C cancelled, R rescheduled; appointment duration 30 minutes.
BILL: amount is integer cents. VISIT references VIS.ID in the same site.
JRN: transaction sequence; D deletes the entire referenced source entity.
No clinician identities, payer coverage, immunizations or vitals are included in this delivery.
"""

ADDENDUM = """Briar delivery support note 3.7 (2026-09-30)
Physical layouts are 3.7. Do not assume the old export guide has been revised.
Sites A (Briar Main) and B (Briar Outreach) were separate installations until 2024.
The workstation timezone setting is America/Chicago at both sites.
LAB REV is a whole integer; larger REV wins, not the last physical line.
JRN deletions take precedence over snapshot records, including laboratory results.
Exported continuation segments are padded to 72 columns; remove right padding only.
MED H was repurposed during the e-prescribing upgrade. Ask pharmacy about historical extracts.
BILL service-date cutover for B was 20260101: B amounts after that date are decimal dollars.
Before that date and at A, amounts are cents. A credit is negative and is not a debit charge.
Unit migration at Outreach was scheduled for 20260101. Legacy instruments may still send old units.
The delivery cannot disambiguate repeated DST wall-clock times without an offset or encounter log.
"""


def generate(out: Path, patients: int = 320, seed: int = 2626) -> None:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    rows = {name: [] for name in SCHEMA}
    truth = {"patients": {}, "labs": {}, "meds": {}, "charges": {}, "notes": {}, "visits": {}, "appointments": {}, "diagnoses": {}, "allergies": {}, "seed": seed}
    jseq = 0
    def add(table, **p):
        p = {"RT": table[:2], **p}
        rows[table].append(p)
        return p
    for i in range(patients):
        site = "AB"[i % 2]
        chart = f"{i // 2 + 1:06}"
        pkey = site + "|" + chart
        ident = f"{i + 1:08}"
        dob = f"{rng.randint(1932, 2009):04}{rng.randint(1,12):02}{rng.randint(1,28):02}"
        if i % 79 == 0:
            dob = ""
        elif i % 83 == 0:
            dob = "250101"  # source cannot establish 1925 versus 2025
        name = f"FICTITIOUS{i:04},PERSON{i:04}"
        if i in (7, 9):
            name, dob = "FICTITIOUSTWIN,PERSON", "19780512"
        allergy = "PENICILLIN:RASH" if i % 11 == 0 else ""
        nka = "Y" if not allergy or i % 22 == 0 else "N"
        add("REG", SITE=site, CHART=chart, NAME=name, DOB=dob, SEX="MF"[i % 2], NKA=nka, ALLERGY=allergy)
        truth["patients"][pkey] = {"dob": dob if len(dob) == 8 else None, "allergy": allergy,
                                     "nka": nka == "Y" and not allergy, "name": name}
        if allergy:
            truth["allergies"][pkey] = allergy
        day, tm = "20261010", "1015"
        if i % 61 == 0:
            tm = "2461"
        elif i % 67 == 0:
            day, tm = "20251102", "0130"
        elif i % 71 == 0:
            day, tm = "20260308", "0230"
        elif i % 73 == 0:
            tm = "2400"
        add("VIS", SITE=site, ID=ident, CHART=chart, DAY=day, TIME=tm, STATUS="F")
        visit_time = None
        if tm == "1015": visit_time = "2026-10-10T15:15:00+00:00"
        if tm == "2400": visit_time = "2026-10-11T05:00:00+00:00"
        truth["visits"][site + "|" + ident] = {"patient": pkey, "utc": visit_time}
        # Physical revision order is intentionally unreliable.
        for test in ("GLU", "K", "CULT"):
            unit = ("mmol/L" if site == "B" and i % 5 else "mg/dL") if test == "GLU" else ""
            if test == "GLU":
                result = "6.2H" if unit == "mmol/L" else "112H"
                if i % 19 == 0: result, unit = "999999", ""  # missing numeric sentinel, not six-digit glucose
                elif i % 17 == 0: result = ">33.3H" if unit == "mmol/L" else ">600H"
                elif i % 37 == 0: unit = ""
            else:
                result = "4.1" if test == "K" else "NEG"
            deleted = test == "K" and i % 41 == 0
            add("LAB", SITE=site, ID=ident, CHART=chart, TEST=test, REV="02", DAY="20261010", TIME="1100", RESULT=result, UNIT=unit, STATUS="C" if test == "GLU" else "F")
            if test == "GLU":
                add("LAB", SITE=site, ID=ident, CHART=chart, TEST=test, REV="01", DAY="20261010", TIME="1100", RESULT="5.0" if unit == "mmol/L" else "90", UNIT=unit, STATUS="P")
            # Deletion ID includes the test; IDs alone are only accessions.
            if deleted:
                jseq += 1
                add("JRN", SITE=site, SEQ=f"{jseq:06}", TABLE="LAB", ID=ident, ACTION="D")
            truth["labs"][site + "|" + ident + "|" + test] = {"patient": pkey, "result": result,
                "unit": unit or ("mmol/L" if test == "K" else ""), "deleted_accession": i % 41 == 0,
                "status": "corrected" if test == "GLU" else "final", "utc": "2026-10-10T16:00:00+00:00"}
        medstatus = "H" if i % 13 == 0 else ("S" if i % 7 == 0 else "A")
        drug = "MISC" if i % 23 == 0 else "MET"
        add("MED", SITE=site, ID=ident, CHART=chart, DRUG=drug, NAME="UNKNOWN COMPOUND" if drug == "MISC" else "METFORMIN 500 MG", DAY="20261010", STATUS=medstatus, SIG="TAKE ONE TABLET BY MOUTH TWICE DAILY")
        truth["meds"][site + "|" + ident] = {"patient": pkey, "drug": drug, "status": {"A": "active", "S": "stopped", "H": "on-hold"}[medstatus]}
        dx = "HXD" if i % 9 == 0 else "DM2"
        text = "FAMILY HISTORY OF DIABETES" if dx == "HXD" else "TYPE 2 DIABETES"
        add("DX", SITE=site, ID=ident, CHART=chart, CODE=dx, TEXT=text, STATUS="A")
        truth["diagnoses"][site + "|" + ident] = {"patient": pkey, "code": dx, "text": text}
        # Two segments, order reversed in the physical file. One full-width segment cannot prove truncation.
        segments = [f"SYNTHETIC FOLLOW-UP FOR {pkey}. NO REAL PATIENT DATA.",
                    "  PLAN: REVIEW LABS. ".ljust(72, "X")]
        for seq in (2, 1):
            add("NOTE", SITE=site, ID=ident, CHART=chart, SEQ=f"{seq:02}", DAY="20261010", TIME="1200", TEXT=segments[seq - 1])
        truth["notes"][site + "|" + ident] = {"patient": pkey, "text": "\n".join(segments)}
        apptstatus = "R" if i % 17 == 0 else "B"
        add("APPT", SITE=site, ID=ident, CHART=chart, DAY="20261020", TIME="1400", STATUS=apptstatus)
        truth["appointments"][site + "|" + ident] = {"patient": pkey, "status": "booked" if apptstatus == "B" else None}
        bill_day = "20251215" if site == "B" and i % 4 == 1 else "20261010"
        amount = "125.50" if site == "B" and bill_day >= "20260101" else "12550"
        if i % 29 == 0: amount = "-25.00" if site == "B" and bill_day >= "20260101" else "-2500"
        add("BILL", SITE=site, ID=ident, CHART=chart, VISIT=ident, DAY=bill_day, AMOUNT=amount, CODE="OFFICE")
        truth["charges"][site + "|" + ident] = {"patient": pkey, "visit": site + "|" + ident, "amount": -25.0 if i % 29 == 0 else 125.50}
    layouts = ["# BRIAR LAYOUT VERSION 3.7", "FILE|RT|FIELD|START|LEN|TYPE|DESC"]
    for table, fields in SCHEMA.items():
        pos = 1
        for name, width in fields:
            layouts.append(f"{table}|{table[:2]}|{name}|{pos}|{width}|T|{name}")
            pos += width
        lines = []
        for row in rows[table]:
            vals = [str(row.get(name, "")) for name, _ in fields]
            assert all(len(v) <= w for v, (_, w) in zip(vals, fields))
            lines.append("".join(v.ljust(w) for v, (_, w) in zip(vals, fields)))
        (out / (table + ".TXT")).write_bytes(("\n".join(lines) + "\n").encode("latin-1"))
    (out / "LAYOUTS.DAT").write_text("\n".join(layouts) + "\n")
    (out / "DATADICT.TXT").write_text(DOCUMENT)
    (out / "SUPPORT.TXT").write_text(ADDENDUM)
    (out / "STAFF.TXT").write_text("registration: Mira Vale, records lead\nlab: Tomas Reed, lab supervisor\npharmacy: Anya Moss, pharmacy analyst\nsystems: Glen Pike, interfaces\nbilling: Inez Fern, revenue analyst\n")
    (out / "CROSSWALKS.TXT").write_text("Synthetic illustrative mappings, not a licensed vocabulary.\nLAB GLU=2345-7 K=2823-3 CULT=630-4\nLAB default units GLU=mg/dL K=mmol/L CULT=(none)\nMED MET=860975; MISC=(unmapped)\nDX DM2=E11.9; HXD=(not classified; preserve text)\nBILL OFFICE=99213\nNOTE type=11506-3\n")
    (out / "manifest.json").write_text(json.dumps({"source": "briar", "version": "3.7", "asOf": "2026-10-26", "seed": seed, "counts": {t: len(r) for t, r in rows.items()}}, indent=2))
    (out / "grading").mkdir(exist_ok=True)
    (out / "grading" / "truth.json").write_text(json.dumps(truth, indent=2, sort_keys=True))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--patients", type=int, default=320)
    p.add_argument("--seed", type=int, default=2626)
    args = p.parse_args()
    generate(args.out, args.patients, args.seed)
