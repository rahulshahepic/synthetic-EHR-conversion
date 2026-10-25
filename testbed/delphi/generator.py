"""Seeded, event-sourced generator for a Delphi export (fixed-width text
extracts + journal + dictionaries + answer key).

The generator simulates a chronological journal of departmental events
(registrations, visits, orders, results, notes, charges) from a seed, then
materializes the fixed-width extracts from that journal. The journal is also
shipped in the export (``JOURNAL.TXT``) as the system's change feed.
Deterministic for a given (seed, patients, as_of). Every planted data-quality
problem is recorded in answer_key/issues.jsonl so tests can measure what
Bridge detects.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import dictionary, layouts, vocab as V

GENERATOR_VERSION = "1.0"
# Delphi stores years as two digits. Year values below the pivot are 20xx,
# values at or above it are 19xx. Documented in the export manifest notes.
PIVOT_YEAR = 30

NICKNAMES = {"JAMES": "JIM", "ROBERT": "BOB", "MICHAEL": "MIKE", "WILLIAM": "BILL", "MARY": "MARIE"}


@dataclass
class Config:
    seed: int = 42
    patients: int = 500
    as_of: date = date(2026, 9, 30)
    # injection rates for planted problems
    rates: dict[str, float] = field(default_factory=lambda: {
        "lab_only": 0.03, "duplicate_registration": 0.03,
        "name_initial": 0.30, "name_typo": 0.15, "name_nickname": 0.20,
        "dob_swapped": 0.08, "dob_blank": 0.02, "sex_blank": 0.10,
        "addr_change": 0.12, "nka_conflict": 0.08,
        "visit_xx": 0.02, "missing_discharge": 0.10, "orphan_provider": 0.01,
        "free_text_dx": 0.08, "julian_invalid": 0.015, "julian_shift": 0.01,
        "time_invalid": 0.01, "note_long": 0.01, "report_long": 0.02,
        "appt_rescheduled": 0.06, "npi_missing": 0.45, "npi_bad": 0.03,
        "rel_blank": 0.05, "charge_supp": 0.02, "lab_misc": 0.03, "lab_comparator": 0.05,
    })


def ymd6(d: date) -> str:
    """A date as Delphi writes it: YYMMDD."""
    return d.strftime("%y%m%d")


def minutes(dt: datetime) -> str:
    return str(dt.hour * 60 + dt.minute)


def npi_check_digit(first9: str) -> str:
    digits = [int(c) for c in "80840" + first9]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


class Generator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.r = random.Random(cfg.seed)
        self.records: dict[str, list[str]] = defaultdict(list)   # file stem -> rendered lines
        self.journal: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.truth: dict[str, dict[str, Any]] = defaultdict(dict)
        self.persons: dict[str, list[str]] = {}
        self._seq: dict[str, int] = defaultdict(int)
        self.providers: list[dict[str, str]] = []

    # ------------------------------------------------------------- utilities
    def chance(self, key: str) -> bool:
        return self.r.random() < self.cfg.rates[key]

    def nid(self, prefix: str, width: int) -> str:
        self._seq[prefix] += 1
        return f"{prefix}{self._seq[prefix]:0{width}d}"

    def plant(self, kind: str, table: str, key: str, **detail: Any) -> None:
        self.issues.append({"type": kind, "table": table, "key": key, **detail})

    def rand_date(self, start: date, end: date) -> date:
        if end <= start:
            return start
        return start + timedelta(days=self.r.randrange((end - start).days + 1))

    def phone(self) -> tuple[str, str]:
        a, b, c = self.r.randint(201, 989), self.r.randint(200, 999), self.r.randint(0, 9999)
        e164 = f"+1{a}{b}{c:04d}"
        fmt = self.r.choice([
            f"({a}) {b}-{c:04d}", f"{a}-{b}-{c:04d}", f"{a}.{b}.{c:04d}", f"{a}{b}{c:04d}",
            f"{a}{b}{c:04d}x{self.r.randint(1, 99)}", f"{b}-{c:04d}",
        ])
        return fmt, e164

    def emit(self, file: str, rt: str, values: dict[str, str], when: datetime, key: str,
             op: str = "A") -> None:
        """Materialize one record and append its journal entry."""
        self.records[file].append(layouts.format_record(file, rt, values))
        self.journal.append({"op": op, "file": file, "key": key, "when": when,
                             "field": "", "value": "", "summary": f"{rt} {key}"})

    def emit_change(self, acct: str, field_name: str, value: str, journal_value: str,
                    when: datetime) -> None:
        self.journal.append({"op": "C", "file": "REG", "key": acct, "when": when,
                             "field": field_name, "value": journal_value, "summary": ""})

    # ------------------------------------------------------------- run
    def run(self, out: Path) -> dict[str, Any]:
        out.mkdir(parents=True, exist_ok=True)
        self.gen_providers()
        for _ in range(self.cfg.patients):
            self.gen_person()
        self.gen_test_account()
        return self.write(out)

    # ------------------------------------------------------------- reference data
    def gen_providers(self, n: int = 30) -> None:
        specs = list(V.SPECIALTY_TEXT)
        for _ in range(n):
            code = self.nid("DR", 4)
            sex = self.r.choice("FM")
            first = self.r.choice(V.FIRST_NAMES_F if sex == "F" else V.FIRST_NAMES_M)
            last = self.r.choice(V.LAST_NAMES)
            spec = self.r.choice(specs)
            cred = {"nurse-practitioner": "NP", "physician-assistant": "PA"}.get(
                spec, self.r.choice(["MD", "MD", "DO"]))
            npi = ""
            billing = "Y" if spec != "other" else "N"
            if not self.chance("npi_missing"):
                first9 = f"1{self.r.randint(0, 99_999_999):08d}"
                npi = first9 + npi_check_digit(first9)
                if self.chance("npi_bad"):
                    npi = npi[:9] + str((int(npi[9]) + 1) % 10)
                    self.plant("npi_invalid", "PROV", code)
            elif billing == "Y":
                self.plant("npi_missing_billing", "PROV", code)
            active = "N" if self.r.random() < 0.1 else "Y"
            row = {"RT": "D", "CODE": code,
                   "NAME": f"{last.upper()}, {first.upper()} {self.r.choice('ABCDEJKLMRST')} {cred}",
                   "SPEC": self.r.choice(V.SPECIALTY_TEXT[spec]), "NPI": npi,
                   "ACT": active, "BILL": billing}
            self.records["PROV"].append(layouts.format_record("PROV", "D", row))
            self.truth["provider_specialty"][code] = spec
            self.providers.append(row)

    def gen_test_account(self) -> None:
        """A registration test account, added to the journal and deleted again;
        it never reaches the extracts."""
        when = datetime(2024, 1, 2, 9, 0)
        self.journal.append({"op": "A", "file": "REG", "key": "R999999", "when": when,
                             "field": "", "value": "", "summary": "A TEST ACCOUNT"})
        self.journal.append({"op": "D", "file": "REG", "key": "R999999",
                             "when": when + timedelta(days=1), "field": "", "value": "",
                             "summary": "D TEST ACCOUNT"})

    # ------------------------------------------------------------- persons
    def canonical_person(self) -> dict[str, Any]:
        r, cfg = self.r, self.cfg
        sex = r.choice("FM")
        first = r.choice(V.FIRST_NAMES_F if sex == "F" else V.FIRST_NAMES_M)
        middle = r.choice(V.FIRST_NAMES_F if sex == "F" else V.FIRST_NAMES_M) if r.random() < 0.6 else ""
        last = r.choice(V.LAST_NAMES)
        lo, hi = r.choice([(0, 17), (18, 64), (18, 64), (65, 95), (65, 95), (96, 104), (30, 60)])
        dob = self.rand_date(date(cfg.as_of.year - hi - 1, cfg.as_of.month, 1),
                             date(cfg.as_of.year - lo, cfg.as_of.month, 1))
        city, state, zip3 = r.choice(V.CITIES)
        addr = {"line1": f"{r.randint(10, 9999)} {r.choice(V.STREETS)}",
                "line2": r.choice(["", "", "", f"APT {r.randint(1, 40)}"]),
                "city": city, "state": state, "zip": f"{zip3}{r.randint(10, 99)}"}
        return {"sex": sex, "first": first, "middle": middle, "last": last, "dob": dob,
                "ssn4": f"{r.randint(0, 9999):04d}", "addr": addr, "phone": self.phone(),
                "race": r.choice(V.RACE_TEXT),
                "deceased": self.rand_date(date(2019, 1, 1), cfg.as_of) if (cfg.as_of - dob).days > 80 * 365
                and r.random() < 0.1 else None}

    def dept_name(self, p: dict[str, Any], dept: str, acct: str) -> str:
        """The person's name as one department recorded it (before the 30-char
        field truncates it). Plants a name_variant when it differs."""
        full = f"{p['last'].upper()},{p['first'].upper()}" + (f" {p['middle'].upper()}" if p["middle"] else "")
        name = full
        if dept == "LAB" and self.chance("name_initial"):
            name = f"{p['last'].upper()},{p['first'].upper()[0]}"
        elif dept == "RAD" and self.chance("name_typo") and len(p["last"]) > 3:
            last = p["last"]
            i = self.r.randrange(1, len(last) - 1)
            swapped = last[:i] + last[i + 1] + last[i] + last[i + 2:]
            name = full.replace(p["last"].upper(), swapped.upper(), 1)
        elif dept == "PHA" and self.chance("name_nickname"):
            nick = NICKNAMES.get(p["first"].upper())
            if nick:
                name = full.replace(p["first"].upper(), nick, 1)
        if name != full:
            self.plant("name_variant", "ACCT", acct, dept=dept)
        return name

    def dept_dob(self, p: dict[str, Any], dept: str, acct: str) -> str:
        """The person's DOB as one department recorded it, YYMMDD."""
        dob = p["dob"]
        if self.chance("dob_blank"):
            self.plant("missing_dob", "ACCT", acct, dept=dept)
            return ""
        if dept in ("RAD", "PHA") and self.chance("dob_swapped") and dob.day <= 12:
            self.plant("dob_variant", "ACCT", acct, dept=dept)
            return f"{dob.year % 100:02d}{dob.day:02d}{dob.month:02d}"
        return ymd6(dob)

    def open_account(self, dept: str, p: dict[str, Any], when: date, person_id: str) -> str:
        prefix = V.ACCOUNT_DEPTS[dept][0]
        acct = f"{prefix}{self._seq[f'ACCT{dept}'] + 1:06d}"
        self._seq[f"ACCT{dept}"] += 1
        name = self.dept_name(p, dept, acct) if dept != "REG" else (
            f"{p['last'].upper()},{p['first'].upper()}" + (f" {p['middle'].upper()}" if p["middle"] else ""))
        if len(name) > 30:
            self.plant("truncated_name", "ACCT", acct, dept=dept)
        dob = ymd6(p["dob"]) if dept == "REG" else self.dept_dob(p, dept, acct)
        if p["dob"].year < 1900 + PIVOT_YEAR:
            self.plant("century_window_dob", "ACCT", acct, dept=dept, true_dob=p["dob"].isoformat())
        sex = p["sex"]
        if dept != "REG" and self.chance("sex_blank"):
            sex = ""
        ssn4 = p["ssn4"]
        if dept == "LAB" and self.r.random() < 0.40:
            ssn4 = ""
        elif dept == "RAD" and self.r.random() < 0.50:
            ssn4 = ""
        elif dept == "PHA" and self.r.random() < 0.30:
            ssn4 = ""
        dt = datetime(when.year, when.month, when.day, 9, 0)
        if dept == "REG":
            a = p["addr"]
            payer = "" if self.r.random() < 0.15 else self.r.choice(list(V.PAYERS))
            algy = ""
            if p["allergies"]:
                algy = ",".join(p["allergies"])
                if self.chance("nka_conflict"):
                    algy = "NKA," + algy
                    self.plant("nka_conflict", "ACCT", acct, reason="NKA recorded alongside allergies")
            elif self.r.random() < 0.5:
                algy = "NKA"
            for i, tok in enumerate(p["allergies"]):
                self.truth["allergy"][f"{acct}-{i + 1}"] = V.ALLERGENS[tok]
            p["payer"], p["algy"] = payer, algy
            rel = ""
            if payer:
                age = (self.cfg.as_of - p["dob"]).days // 365
                rel = "C" if age < 18 else self.r.choice(["S", "S", "S", "P", "O"])
                if self.chance("rel_blank"):
                    rel = ""
                    self.plant("missing_relationship", "REG", f"COV-{acct}")
            values = {"RT": "A", "ACCT": acct, "NAME": name, "DOB": dob, "SEX": sex, "SSN4": ssn4,
                      "ADDR1": a["line1"], "ADDR2": a["line2"], "CITY": a["city"], "STATE": a["state"],
                      "ZIP": a["zip"], "PHONE": p["phone"][0], "REGDATE": ymd6(when),
                      "DEATH": ymd6(p["deceased"]) if p["deceased"] else "",
                      "RACE": p["race"], "PAYER": payer,
                      "MEMBER": f"M{self.r.randint(10**8, 10**9 - 1)}" if payer else "",
                      "REL": rel, "ALGY": algy}
            self.emit("REG", "A", values, dt, acct)
        else:
            values = {"RT": "A", "ACCT": acct, "NAME": name, "DOB": dob, "SEX": sex,
                      "SSN4": ssn4, "OPEN": ymd6(when)}
            self.emit(dept, "A", values, dt, acct)
        self.plant_dup(person_id, dept, acct)
        return acct

    def plant_dup(self, person_id: str, dept: str, acct: str) -> None:
        if dept != "REG":
            self.plant("cross_department_duplicate", "ACCT", acct, dept=dept, person=person_id)

    def gen_person(self) -> None:
        r, cfg = self.r, self.cfg
        person_id = self.nid("PERSON", 5)
        p = self.canonical_person()
        p["_person_id"] = person_id
        p["allergies"] = self.pick_allergies()
        p["conditions"] = self.pick_conditions(p)
        self.truth["person"][person_id] = {"first": p["first"], "last": p["last"],
                                           "dob": p["dob"].isoformat(), "sex": p["sex"]}
        reg_date = self.rand_date(max(date(1995, 1, 1), p["dob"] + timedelta(days=30)),
                                  cfg.as_of - timedelta(days=30))
        accounts: dict[str, str] = {}
        acct_ids: list[str] = []
        has_reg = not self.chance("lab_only")
        reg_acct = ""
        if has_reg:
            reg_acct = self.open_account("REG", p, reg_date, person_id)
            accounts["REG"] = reg_acct
            acct_ids.append(reg_acct)
            if self.chance("duplicate_registration"):
                dup = self.open_account("REG", p, reg_date + timedelta(days=r.randint(30, 900)), person_id)
                acct_ids.append(dup)
                self.plant("duplicate_registration", "ACCT", dup, duplicate_of=reg_acct, person=person_id)
                reg_acct = dup  # later activity lands on the newer chart, as it does
        p["_accounts"] = accounts
        p["_acct_ids"] = acct_ids
        p["_reg_acct"] = reg_acct

        end = p["deceased"] or cfg.as_of
        cursor = reg_date
        visits = []
        if has_reg:
            for _ in range(r.randint(1, 5)):
                cursor = self.rand_date(cursor, min(end, cursor + timedelta(days=900)))
                if cursor >= end:
                    break
                visits.append(self.gen_visit(p, reg_acct, cursor))
        # chronic problems are recorded once, on an early visit or none;
        # problems live in the registration chart, so lab-only persons have none
        if has_reg:
            for code in p["conditions"]:
                self.gen_dx(p, reg_acct, r.choice(visits) if visits else "", code, cursor)
        if has_reg and r.random() < 0.5:
            self.gen_meds_for_conditions(p)
        if not has_reg:
            # lab-only person: a couple of standalone panels, nothing else exists
            for _ in range(r.randint(1, 2)):
                when = self.rand_date(reg_date, end)
                self.gen_labs(p, "", datetime(when.year, when.month, when.day, 10, 0))
        for _ in range(r.choice([0, 1, 1, 2])):
            if has_reg:
                self.gen_appointment(p, reg_acct, end)
        if has_reg and self.chance("addr_change"):
            self.gen_addr_change(p, reg_acct, reg_date, end)
        self.persons[person_id] = acct_ids

    def pick_conditions(self, p: dict[str, Any]) -> list[str]:
        age = (self.cfg.as_of - p["dob"]).days // 365
        pool = V.CHRONIC_POOL if age >= 18 else ["ASTH", "UTI"]
        return self.r.sample(pool, k=min(len(pool), self.r.choice([0, 1, 1, 2, 3, 4])))

    def pick_allergies(self) -> list[str]:
        if self.r.random() > 0.35:
            return []
        return self.r.sample(list(V.ALLERGENS), k=self.r.choice([1, 1, 2]))

    def gen_addr_change(self, p: dict[str, Any], reg_acct: str, reg_date: date, end: date) -> None:
        r = self.r
        when = self.rand_date(reg_date + timedelta(days=30), end)
        dt = datetime(when.year, when.month, when.day, 10, 0)
        city, state, zip3 = r.choice(V.CITIES)
        a = {"line1": f"{r.randint(10, 9999)} {r.choice(V.STREETS)}",
             "line2": r.choice(["", "", f"APT {r.randint(1, 40)}"]),
             "city": city, "state": state, "zip": f"{zip3}{r.randint(10, 99)}"}
        joined = "^".join([a["line1"], a["line2"], a["city"], a["state"], a["zip"]])
        phone, e164 = self.phone()
        self.emit_change(reg_acct, "ADDR", joined, joined, dt)
        self.emit_change(reg_acct, "PHONE", phone, phone, dt)
        self.truth["a08_demographics"][reg_acct] = {"addr": joined, "phone": e164}

    # ------------------------------------------------------------- chart
    def account_for(self, dept: str, p: dict[str, Any], when: date, person_id: str = "") -> str:
        if dept not in p["_accounts"]:
            p["_accounts"][dept] = self.open_account(dept, p, when, person_id or p["_person_id"])
            p["_acct_ids"].append(p["_accounts"][dept])
        return p["_accounts"][dept]

    def gen_visit(self, p: dict[str, Any], reg_acct: str, day: date) -> str:
        r = self.r
        vid = self.nid("V", 7)
        cls = r.choices(list(V.VISIT_CLASS_WEIGHTS), weights=list(V.VISIT_CLASS_WEIGHTS.values()))[0]
        if self.chance("visit_xx"):
            cls = "XX"
            self.plant("unknown_visit_type", "ENC", vid)
        truth_cls = V.VISIT_CLASSES[cls]
        unit = V.CLASS_UNIT[truth_cls]
        admit = datetime(day.year, day.month, day.day,
                         *(lambda m: (m // 60, m % 60))(r.randint(0, 1439) if truth_cls in ("emergency", "inpatient")
                                                        else r.randint(420, 1080)))
        disch = None
        if truth_cls == "inpatient":
            disch = admit + timedelta(hours=r.randint(24, 24 * 7))
            if self.chance("missing_discharge"):
                disch = None
                self.plant("missing_discharge", "ENC", vid)
        elif truth_cls == "observation":
            disch = admit + timedelta(hours=r.randint(8, 30))
        elif truth_cls in ("ambulatory", "emergency"):
            disch = admit + timedelta(minutes=r.randint(30, 300))
        status = "X" if r.random() < 0.04 else "C"
        prov = r.choice(self.providers)["CODE"]
        if self.chance("orphan_provider"):
            prov = "DR9999"
            self.plant("orphan_provider", "ENC", vid)
        values = {"RT": "V", "VISIT": vid, "ACCT": reg_acct, "UNIT": unit, "CLASS": cls,
                  "ADMITD": ymd6(admit.date()), "ADMITT": minutes(admit),
                  "DISD": ymd6(disch.date()) if disch else "",
                  "DIST": minutes(disch) if disch else "",
                  "PROV": prov, "STATUS": status, "REASON": r.choice(V.REASONS)}
        self.emit("ENC", "V", values, admit, vid)
        self.truth["visit_class"][vid] = truth_cls
        if status == "C":
            self.gen_chart(p, reg_acct, vid, admit, truth_cls)
        return vid

    def gen_chart(self, p: dict[str, Any], reg_acct: str, vid: str, admit: datetime,
                  truth_cls: str | None) -> None:
        r = self.r
        if self.chance("free_text_dx"):
            self.gen_dx(p, reg_acct, vid, "", admit.date())
        if r.random() < 0.5:
            self.gen_labs(p, vid, admit)
        if r.random() < 0.25:
            self.gen_rad(p, vid, admit)
        if r.random() < 0.5:
            self.gen_note(p, reg_acct, vid, admit)
        codes = V.VISIT_CHARGES.get(truth_cls or "ambulatory", V.VISIT_CHARGES["ambulatory"])
        picks = r.sample(codes, k=min(len(codes), r.randint(1, 3)))
        if self.chance("charge_supp"):
            picks.append("SUPP")
        for code in picks:
            cid = self.nid("B", 7)
            post = admit.date() + timedelta(days=r.randint(0, 5))
            values = {"RT": "B", "CHG": cid, "ACCT": reg_acct, "VISIT": vid, "CODE": code,
                      "QTY": "1", "AMOUNT": str(V.CHARGES[code][2] * 100), "POST": ymd6(post)}
            self.emit("BILL", "B", values, datetime(post.year, post.month, post.day, 12, 0), cid)
            if V.CHARGES[code][1] is None:
                self.plant("unmappable_charge", "BILL", cid, code=code)
        if r.random() < 0.3:
            self.gen_meds_acute(p, vid, admit)

    def gen_dx(self, p: dict[str, Any], reg_acct: str, vid: str, code: str, when: date) -> None:
        r = self.r
        dxid = self.nid("DX", 6)
        onset = self.rand_date(max(p["dob"], when - timedelta(days=3650)), when)
        if code:
            text = V.DX_SHORTHAND[code][0]
            status = r.choices(["A", "I", "R", ""], weights=[70, 10, 15, 5])[0]
            self.truth["dx"][dxid] = V.DX_SHORTHAND[code][1]
            self.plant("shorthand_dx", "DX", dxid, code=code)
        else:
            text = r.choice(V.FREE_TEXT_DX)
            status = "A"
            self.plant("free_text_dx", "DX", dxid)
        values = {"RT": "P", "DXID": dxid, "ACCT": reg_acct, "VISIT": vid, "CODE": code,
                  "TEXT": text, "STATUS": status, "ONSET": ymd6(onset),
                  "RESOLV": ymd6(self.rand_date(onset, self.cfg.as_of)) if status == "R" else ""}
        self.emit("DX", "P", values, datetime(when.year, when.month, when.day, 11, 0), dxid)

    def gen_labs(self, p: dict[str, Any], vid: str, admit: datetime) -> None:
        r = self.r
        lab_acct = self.account_for("LAB", p, admit.date())
        acc = self.nid("A", 8)
        collect = admit + timedelta(minutes=r.randint(10, 90))
        tests = r.sample([c for c in V.LABS if c != "MISC"], k=r.randint(1, 6))
        if self.chance("lab_misc"):
            tests.append("MISC")
        for code in tests:
            desc, loinc, unit, (lo, hi), typical, kind = V.LABS[code]
            res_id = f"{acc}:{code}"
            if kind == "num":
                val = round(r.uniform(*typical), 1 if typical[1] < 50 else 0)
                flag = ""
                if hi and val > float(hi):
                    flag = "H"
                elif lo and val < float(lo):
                    flag = "L"
                sval = f"{val:g}{flag}"
                if flag:
                    self.plant("flag_string_result", "LAB", res_id, value=sval)
                if self.chance("lab_comparator"):
                    sval = r.choice([f"<{lo}", f">{typical[1]:g}"])
                    self.plant("lab_comparator_value", "LAB", res_id, value=sval)
            elif kind == "coded":
                sval = r.choice(["NEG", "NEG", "POS", "TRACE"])
            else:
                sval = r.choice(["FAXED TO MD", "PENDING REVIEW", "ABNORMAL CALL LAB"])
                self.plant("unmappable_lab", "LAB", res_id, code=code)
            year, yday, mins = collect.year % 100, collect.timetuple().tm_yday, collect.hour * 60 + collect.minute
            if self.chance("julian_invalid"):
                yday = yday + 400
                self.plant("invalid_julian_date", "LAB", res_id, yday=yday)
            elif self.chance("julian_shift") and yday > 30:
                yday = yday - 30
                self.plant("julian_date_shift", "LAB", res_id, yday=yday)
            if self.chance("time_invalid"):
                mins = 1440 + r.randint(0, 600)
                self.plant("invalid_time_minutes", "LAB", res_id, minutes=mins)
            values = {"RT": "R", "ACCT": lab_acct, "ACC": acc, "TEST": code, "RESULT": sval,
                      "YEAR": f"{year:02d}", "YDAY": str(yday), "TIME": str(mins)}
            self.emit("LAB", "R", values, collect, acc)
            self.truth["lab"][res_id] = loinc
            if self.r.random() < 0.02:
                # entered in error: the journal shows the add and the delete;
                # the extract record above is what the night batch had already sent.
                self.journal.append({"op": "D", "file": "LAB", "key": acc,
                                     "when": collect + timedelta(hours=3), "field": "",
                                     "value": "", "summary": "D ENTERED IN ERROR"})

    def gen_rad(self, p: dict[str, Any], vid: str, admit: datetime) -> None:
        r = self.r
        rad_acct = self.account_for("RAD", p, admit.date())
        exam = self.nid("X", 7)
        when = admit + timedelta(minutes=r.randint(30, 240))
        report = r.choice(V.REPORT_LINES)
        if self.chance("report_long"):
            report = " ".join(r.choices(V.REPORT_LINES, k=4)) + " COMPARISON: NONE AVAILABLE."
            self.plant("truncated_report", "RAD", exam)
        xcode = r.choice(list(V.EXAM_CODES))
        values = {"RT": "X", "ACCT": rad_acct, "EXAM": exam, "XCODE": xcode,
                  "DATE": ymd6(when.date()), "TIME": minutes(when), "REPORT": report}
        self.emit("RAD", "X", values, when, exam)

    def gen_note(self, p: dict[str, Any], reg_acct: str, vid: str, admit: datetime) -> None:
        r = self.r
        note = self.nid("N", 7)
        lines = r.choices(V.NOTE_LINES, k=r.randint(2, 4))
        if self.chance("note_long"):
            lines = r.choices(V.NOTE_LINES, k=12)
            self.plant("truncated_note", "NOTE", note)
        shipped = lines[:8]  # the extract carries at most 8 continuation records
        when = admit + timedelta(minutes=r.randint(60, 600))
        header = {"RT": "N", "NOTE": note, "ACCT": reg_acct, "VISIT": vid,
                  "TYPE": r.choice(V.NOTE_TYPES), "DATE": ymd6(when.date()), "TIME": minutes(when),
                  "PROV": r.choice(self.providers)["CODE"], "NLINES": str(len(shipped))}
        self.emit("NOTE", "N", header, when, note)
        for i, line in enumerate(shipped, 1):
            self.records["NOTE"].append(layouts.format_record(
                "NOTE", "C", {"RT": "C", "NOTE": note, "SEQ": str(i), "TEXT": line}))

    def gen_meds_for_conditions(self, p: dict[str, Any]) -> None:
        r = self.r
        ndcs = [r.choice(V.CHRONIC_MEDS[c]) for c in p["conditions"] if c in V.CHRONIC_MEDS]
        for ndc in ndcs:
            self.gen_med(p, ndc, acute=False)

    def gen_meds_acute(self, p: dict[str, Any], vid: str, admit: datetime) -> None:
        self.gen_med(p, self.r.choice(V.ACUTE_NDCS), acute=True, when=admit.date())

    def gen_med(self, p: dict[str, Any], ndc: str, acute: bool, when: date | None = None) -> None:
        r = self.r
        pha_acct = self.account_for("PHA", p, when or self.cfg.as_of - timedelta(days=365))
        oid = self.nid("M", 7)
        name, rx, doses, sigs, flag = V.FORMULARY[ndc]
        start = when or self.rand_date(max(p["dob"], date(2015, 1, 1)), self.cfg.as_of - timedelta(days=30))
        status = "C" if acute else r.choices(["A", "D"], weights=[85, 15])[0]
        values = {"RT": "M", "ACCT": pha_acct, "ORD": oid, "NDC": ndc, "DRUG": name,
                  "DOSE": r.choice(doses), "SIG": r.choice(sigs), "START": ymd6(start),
                  "STOP": ymd6(start + timedelta(days=10)) if acute else "",
                  "STATUS": status, "PROV": r.choice(self.providers)["CODE"]}
        self.emit("PHA", "M", values, datetime(start.year, start.month, start.day, 13, 0), oid)
        if rx is None:
            self.plant("unmappable_medication", "PHA", oid, code=ndc)
        self.truth["med"][oid] = rx
        if flag and status == "A":
            self.truth["sentinel"].setdefault(f"active_{flag}", []).append(oid)

    def gen_appointment(self, p: dict[str, Any], reg_acct: str, end: date) -> None:
        r = self.r
        aid = self.nid("S", 7)
        future = r.random() < 0.3
        if future:
            when = self.rand_date(self.cfg.as_of + timedelta(days=1), self.cfg.as_of + timedelta(days=120))
            status, truth = "B", "booked"
            if self.chance("appt_rescheduled"):
                status, truth = "R", None
                self.plant("unrepresentable_status", "APPT", aid, status="R")
        else:
            when = self.rand_date(max(p["dob"], date(2015, 1, 1)), end)
            status, truth = r.choices([("C", "fulfilled"), ("N", "noshow"), ("A", "arrived"), ("X", "cancelled")],
                                       weights=[70, 10, 10, 10])[0]
        dt = datetime(when.year, when.month, when.day, *(lambda m: (m // 60, m % 60))(r.randint(480, 1080)))
        values = {"RT": "S", "APPT": aid, "ACCT": reg_acct, "DATE": ymd6(when), "TIME": minutes(dt),
                  "UNIT": r.choice(["CLI", "MED", "DAY"]), "PROV": r.choice(self.providers)["CODE"],
                  "STATUS": status, "REASON": r.choice(["F/U", "PHYSICAL", "NEW PT", "MED CHECK", ""])}
        self.emit("APPT", "S", values, dt, aid)
        self.truth["appt_status"][aid] = truth

    # ------------------------------------------------------------- output
    def write(self, out: Path) -> dict[str, Any]:
        for stem, fname in layouts.FILES.items():
            if stem == "JOURNAL":
                continue
            lines = list(self.records.get(stem, []))
            if stem == "LABDICT":
                lines = [layouts.format_record("LABDICT", "T",
                         {"RT": "T", "TEST": code, "DESC": d[0], "UNIT": d[2], "LOW": d[3][0], "HIGH": d[3][1]})
                         for code, d in V.LABS.items()]
            elif stem == "DXDICT":
                lines = [layouts.format_record("DXDICT", "D", {"RT": "D", "CODE": code, "EXPAND": exp})
                         for code, (exp, _) in V.DX_SHORTHAND.items()]
            elif stem == "CHGDICT":
                lines = [layouts.format_record("CHGDICT", "C",
                         {"RT": "C", "CODE": code, "DESC": d[0], "CPT": d[1] or ""})
                         for code, d in V.CHARGES.items()]
            (out / fname).write_bytes(("\n".join(lines) + ("\n" if lines else "")).encode("latin-1", errors="replace"))

        journal_lines = []
        for i, e in enumerate(sorted(self.journal, key=lambda e: e["when"]), 1):
            journal_lines.append(layouts.format_record("JOURNAL", "J", {
                "RT": "J", "SEQ": str(i), "OP": e["op"], "FILE": e["file"], "KEY": e["key"],
                "DATE": ymd6(e["when"].date()), "TIME": minutes(e["when"]),
                "FIELD": e["field"], "VALUE": e["value"] or e["summary"]}))
        (out / "JOURNAL.TXT").write_bytes(("\n".join(journal_lines) + "\n").encode("latin-1", errors="replace"))
        (out / "LAYOUTS.DAT").write_text(layouts.layouts_dat(), encoding="utf-8")
        (out / "DATADICT.TXT").write_bytes(dictionary.DATADICT_TEXT.encode("latin-1", errors="replace"))

        key = out / "answer_key"
        key.mkdir(exist_ok=True)
        (key / "estate_discrepancies.json").write_text(json.dumps(dictionary.DISCREPANCIES, indent=1))
        with open(key / "issues.jsonl", "w") as f:
            for issue in self.issues:
                f.write(json.dumps(issue) + "\n")
        (key / "persons.json").write_text(json.dumps(self.persons, indent=1))
        (key / "truth.json").write_text(json.dumps(self.truth, indent=1, default=str))

        counts = {stem: len(self.records.get(stem, [])) for stem in layouts.FILES if stem != "JOURNAL"}
        counts["LABDICT"], counts["DXDICT"], counts["CHGDICT"] = len(V.LABS), len(V.DX_SHORTHAND), len(V.CHARGES)
        counts["JOURNAL"] = len(journal_lines)
        issue_counts: dict[str, int] = defaultdict(int)
        for i in self.issues:
            issue_counts[i["type"]] += 1
        manifest = {"system": "Delphi", "generatorVersion": GENERATOR_VERSION, "seed": self.cfg.seed,
                    "patients": self.cfg.patients, "asOf": self.cfg.as_of.isoformat(), "counts": counts,
                    "notes": {
                        "timestamps": "Facility local time (America/Chicago), no offset. Dates are YYMMDD "
                                      "with a pivot year of 30; lab dates are Julian (two-digit year + day "
                                      "of year); times are minutes since midnight.",
                        "charges": "BILL amounts are integer cents.",
                        "identity": "Each department assigns its own account numbers; there is no master "
                                    "patient index. JOURNAL.TXT is the transaction journal (change feed).",
                        "dictionary": "DATADICT.TXT is the vendor data dictionary shipped with the export.",
                    }}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
        return {"counts": counts, "issues": dict(issue_counts)}


def generate(out: Path | str, seed: int = 42, patients: int = 500, as_of: date | None = None) -> dict[str, Any]:
    cfg = Config(seed=seed, patients=patients)
    if as_of:
        cfg.as_of = as_of
    return Generator(cfg).run(Path(out))
