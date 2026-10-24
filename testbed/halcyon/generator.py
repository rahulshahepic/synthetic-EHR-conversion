"""Seeded generator for a Halcyon Classic export (DB + HL7 v2 feeds + CSV extracts + answer key).

Deterministic for a given (seed, patients, as_of). Every planted data-quality problem is
recorded in answer_key/issues.jsonl so tests can measure what Bridge detects.
"""
from __future__ import annotations

import csv
import json
import random
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import vocab as V

GENERATOR_VERSION = "1.0"
ICD10_CUTOVER = date(2015, 10, 1)


@dataclass
class Config:
    seed: int = 42
    patients: int = 500
    as_of: date = date(2026, 9, 30)
    # injection rates for planted problems
    rates: dict[str, float] = field(default_factory=lambda: {
        "second_facility": 0.25, "duplicate_person": 0.04, "dup_has_a40": 0.5,
        "sex_odd": 0.04, "dob_zero": 0.005, "dob_2digit": 0.01, "mojibake": 0.01,
        "addr_crammed": 0.05, "nka_conflict": 0.08, "nka_row": 0.04,
        "missing_discharge": 0.10, "dst_ambiguous": 0.01, "orphan_provider": 0.01, "visit_xx": 0.01,
        "retired_icd10": 0.04, "local_dx": 0.05, "free_text_dx": 0.05,
        "lab_comparator": 0.02, "lab_text": 0.01, "oru_corrected": 0.03,
        "vital_weight_typo": 0.01, "vital_temp_nodecimal": 0.01, "vital_bp_malformed": 0.01,
        "vital_unit_in_value": 0.03, "note_truncated": 0.01, "immun_date_conflict": 0.05,
        "registry_only": 0.10, "siu_cancel": 0.10, "cob_duplicate": 0.02, "a08_update": 0.05,
        "npi_missing": 0.08, "npi_bad": 0.03,
    })


def d8(d: date) -> str:
    return d.strftime("%Y%m%d")


def dt12(d: datetime) -> str:
    return d.strftime("%Y%m%d%H%M")


def first_sunday_nov(year: int) -> date:
    d = date(year, 11, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7)


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
        self.rows: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.issues: list[dict[str, Any]] = []
        self.truth: dict[str, dict[str, Any]] = defaultdict(dict)
        self.persons: dict[str, list[str]] = {}
        self.feeds: dict[str, list[str]] = {"adt": [], "oru": [], "siu": []}
        self.registry: list[list[str]] = []
        self._seq: dict[str, int] = defaultdict(int)
        self._msg = 0

    # ------------------------------------------------------------- utilities
    def chance(self, key: str) -> bool:
        return self.r.random() < self.cfg.rates[key]

    def nid(self, prefix: str, width: int = 6) -> str:
        self._seq[prefix] += 1
        return f"{prefix}{self._seq[prefix]:0{width}d}"

    def plant(self, kind: str, table: str, key: str, **detail: Any) -> None:
        self.issues.append({"type": kind, "table": table, "key": key, **detail})

    def rand_date(self, start: date, end: date) -> date:
        if end <= start:
            return start
        return start + timedelta(days=self.r.randrange((end - start).days + 1))

    def rand_dt(self, start: date, end: date, hours: tuple[int, int] = (7, 18)) -> datetime:
        d = self.rand_date(start, end)
        return datetime(d.year, d.month, d.day, self.r.randint(*hours), self.r.choice([0, 15, 30, 45]))

    def phone(self) -> tuple[str, str]:
        a, b, c = self.r.randint(201, 989), self.r.randint(200, 999), self.r.randint(0, 9999)
        e164 = f"+1{a}{b}{c:04d}"
        fmt = self.r.choice([
            f"({a}) {b}-{c:04d}", f"{a}-{b}-{c:04d}", f"{a}.{b}.{c:04d}", f"{a}{b}{c:04d}",
            f"{a}{b}{c:04d}x{self.r.randint(1, 99)}", f"{b}-{c:04d}",
        ])
        return fmt, e164

    # ------------------------------------------------------------- run
    def run(self, out: Path) -> dict[str, Any]:
        out.mkdir(parents=True, exist_ok=True)
        self.gen_reference()
        self.gen_providers()
        for _ in range(self.cfg.patients):
            self.gen_person()
        self.gen_users()
        return self.write(out)

    # ------------------------------------------------------------- reference data
    def gen_reference(self) -> None:
        for fid, name, tz, wt, temp, ht in V.FACILITIES:
            self.rows["FACILITY"].append({"FAC_ID": fid, "FAC_NAME": name, "TZ_NOTE": f"local time ({tz.split('/')[-1]})"})
        for did, fac, name, kind in V.DEPTS:
            self.rows["DEPT"].append({"DEPT_ID": did, "FAC_ID": fac or "", "DEPT_NAME": name, "DEPT_KIND": kind})
            if fac is None:
                self.plant("shared_department", "DEPT", did)
        for pid, name in V.PAYERS:
            self.rows["PAYER"].append({"PAYER_ID": pid, "PAYER_NAME": name})
        for plid, pid, name, typ in V.PLANS:
            self.rows["PLAN"].append({"PLAN_ID": plid, "PAYER_ID": pid, "PLAN_NAME": name, "PLAN_TYPE": typ})

    def gen_providers(self, n: int = 40) -> None:
        specs = list(V.SPECIALTY_TEXT)
        self.providers: list[dict[str, str]] = []
        for _ in range(n):
            pid = self.nid("PR", 3)
            sex = self.r.choice("FM")
            first = self.r.choice(V.FIRST_NAMES_F if sex == "F" else V.FIRST_NAMES_M)
            last = self.r.choice(V.LAST_NAMES)
            spec = self.r.choice(specs)
            cred = {"nurse-practitioner": "NP", "physician-assistant": "PA"}.get(spec, self.r.choice(["MD", "MD", "DO"]))
            first9 = f"1{self.r.randint(0, 99_999_999):08d}"
            npi = first9 + npi_check_digit(first9)
            billing = "Y" if spec != "other" else "N"
            if self.chance("npi_missing"):
                npi = ""
                if billing == "Y":
                    self.plant("npi_missing_billing", "PROVIDER", pid)
            elif self.chance("npi_bad"):
                npi = npi[:9] + str((int(npi[9]) + 1) % 10)
                self.plant("npi_invalid", "PROVIDER", pid)
            active = "N" if self.r.random() < 0.1 else "Y"
            row = {
                "PROV_ID": pid, "NAME": f"{last.upper()}, {first.upper()} {self.r.choice('ABCDEJKLMRST')} {cred}",
                "NPI": npi, "SPECIALTY": self.r.choice(V.SPECIALTY_TEXT[spec]), "BILLING_FLAG": billing,
                "ACTIVE": active, "TERM_DT": d8(self.rand_date(date(2018, 1, 1), self.cfg.as_of)) if active == "N" else "",
            }
            self.truth["provider_specialty"][pid] = spec
            self.rows["PROVIDER"].append(row)
            self.providers.append(row)

    def gen_users(self) -> None:
        for p in self.providers:
            last, rest = p["NAME"].split(", ", 1)
            uname = (rest[0] + last.replace(" ", "").replace("'", "").replace(".", ""))[:12].upper()
            self.rows["USERS"].append({"USER_ID": self.nid("U", 4), "USERNAME": uname,
                                       "FULL_NAME": p["NAME"], "PROV_ID": p["PROV_ID"], "ACTIVE": p["ACTIVE"]})
        for g in V.GENERIC_USERS:
            uid = self.nid("U", 4)
            self.rows["USERS"].append({"USER_ID": uid, "USERNAME": g, "FULL_NAME": g, "PROV_ID": "", "ACTIVE": "Y"})
            self.plant("generic_user", "USERS", uid, username=g)
        for _ in range(8):
            first, last = self.r.choice(V.FIRST_NAMES_F + V.FIRST_NAMES_M), self.r.choice(V.LAST_NAMES)
            self.rows["USERS"].append({"USER_ID": self.nid("U", 4), "USERNAME": (first[0] + last)[:12].upper(),
                                       "FULL_NAME": f"{last.upper()}, {first.upper()}", "PROV_ID": "", "ACTIVE": "Y"})

    # ------------------------------------------------------------- persons
    def gen_person(self) -> None:
        r, cfg = self.r, self.cfg
        person_id = self.nid("PERSON", 5)
        sex = r.choice("FM")
        first = r.choice(V.FIRST_NAMES_F if sex == "F" else V.FIRST_NAMES_M)
        middle = r.choice(V.FIRST_NAMES_F if sex == "F" else V.FIRST_NAMES_M) if r.random() < 0.6 else ""
        last = r.choice(V.LAST_NAMES)
        age = r.choice([r.randint(0, 17), r.randint(18, 64), r.randint(18, 64), r.randint(65, 95)])
        dob = self.rand_date(date(cfg.as_of.year - age - 1, cfg.as_of.month, 1), date(cfg.as_of.year - age, cfg.as_of.month, 1))
        city, state, zip3 = r.choice(V.CITIES)
        addr = {"line1": f"{r.randint(10, 9999)} {r.choice(V.STREETS)}", "line2": r.choice(["", "", "", f"APT {r.randint(1, 40)}"]),
                "city": city, "state": state, "zip": f"{zip3}{r.randint(10, 99)}"}
        race = r.choice(list(V.RACE_TEXT))
        p = {"person_id": person_id, "sex": sex, "first": first, "middle": middle, "last": last, "dob": dob,
             "ssn4": f"{r.randint(0, 9999):04d}", "addr": addr, "phone": self.phone(), "cell": self.phone() if r.random() < 0.7 else None,
             "race": race, "deceased": self.rand_date(date(2019, 1, 1), cfg.as_of) if age > 80 and r.random() < 0.1 else None}
        self.truth["person"][person_id] = {"first": first, "last": last, "dob": dob.isoformat(), "sex": sex}

        facs = [r.choice(["FAC1", "FAC1", "FAC2", "FAC3"])]
        if self.chance("second_facility"):
            facs.append(r.choice([f for f in ("FAC1", "FAC2", "FAC3") if f != facs[0]]))
        pat_ids = []
        conditions = self.pick_conditions(age)
        allergies = self.pick_allergies()
        for i, fac in enumerate(facs):
            pat_id = self.add_pat(p, fac, primary=(i == 0), has_allergies=bool(allergies))
            pat_ids.append(pat_id)
            self.gen_chart(pat_id, p, fac, conditions, allergies if i == 0 or r.random() < 0.5 else [], primary=(i == 0))
        if self.chance("duplicate_person"):
            dup_id = self.add_pat(p, facs[0], primary=False, has_allergies=bool(allergies), typo=True)
            pat_ids.append(dup_id)
            self.plant("duplicate_person", "PAT", dup_id, duplicate_of=pat_ids[0], person=person_id)
            self.gen_chart(dup_id, p, facs[0], conditions[:1], [], primary=False, light=True)
            if self.chance("dup_has_a40"):
                self.adt("A40", dup_id, merge_into=pat_ids[0])
                self.plant("a40_merge", "PAT", dup_id, surviving=pat_ids[0])
        self.persons[person_id] = pat_ids
        self.gen_coverage(pat_ids[0], p)

    def add_pat(self, p: dict[str, Any], fac: str, primary: bool, has_allergies: bool, typo: bool = False) -> str:
        r = self.r
        pat_id = self.nid("P")
        self._seq[f"MRN{fac}"] += 1
        mrn = f"{fac[-1]}{self._seq[f'MRN{fac}']:07d}"
        first, last, dob = p["first"], p["last"], p["dob"]
        if typo:
            kind = r.choice(["name", "dob", "first"])
            if kind == "name" and len(last) > 3:
                i = r.randrange(1, len(last) - 1)
                last = last[:i] + last[i + 1] + last[i] + last[i + 2:]
            elif kind == "dob":
                dob = dob.replace(day=dob.month) if dob.month <= 28 else dob + timedelta(days=1)
            else:
                first = {"Mary": "Marie", "James": "Jim", "Robert": "Bob", "Michael": "Mike"}.get(first, first[:-1] + "e")
        name = f"{last.upper()},{first.upper()}" + (f" {p['middle'].upper()}" if p["middle"] else "")
        if self.chance("mojibake") and any(ord(c) > 127 for c in name):
            name = name.encode("utf-8").decode("latin-1")
            self.plant("mojibake_name", "PAT", pat_id)
        dob_s = d8(dob)
        if self.chance("dob_zero"):
            dob_s = "00000000"
            self.plant("invalid_dob", "PAT", pat_id)
        elif self.chance("dob_2digit"):
            dob_s = dob.strftime("%m%d%y")
            self.plant("legacy_dob_format", "PAT", pat_id)
        sex = p["sex"]
        if self.chance("sex_odd"):
            sex = r.choice(["U", "X", "", "O"])
            self.plant("ambiguous_sex", "PAT", pat_id, value=sex)
        a = p["addr"]
        if self.chance("addr_crammed"):
            addr = f"{a['line1']} {a['line2']} {a['city']} {a['state']} {a['zip']}".replace("  ", " ")
            self.plant("crammed_address", "PAT", pat_id)
        else:
            addr = "^".join([a["line1"], a["line2"], a["city"], a["state"], a["zip"]])
        nka = "Y" if not has_allergies else "N"
        if has_allergies and self.chance("nka_conflict"):
            nka = "Y"
            self.plant("nka_conflict", "PAT", pat_id, reason="NKA flag with allergy rows")
        reg = self.rand_date(max(p["dob"], date(2008, 1, 1)), self.cfg.as_of - timedelta(days=30))
        row = {"PAT_ID": pat_id, "MRN": mrn, "FAC_ID": fac, "PAT_NAME": name, "DOB": dob_s, "SEX": sex,
               "RACE": p["race"], "ADDR": addr, "PHONE_HOME": p["phone"][0], "PHONE_CELL": p["cell"][0] if p["cell"] else "",
               "SSN4": p["ssn4"], "DECEASED_DT": d8(p["deceased"]) if p["deceased"] else "", "NKA_FLAG": nka,
               "LAST_UPD": d8(reg)}
        self.rows["PAT"].append(row)
        self._pat_meta = getattr(self, "_pat_meta", {})
        self._pat_meta[pat_id] = {"row": row, "reg": reg, "fac": fac, "person": p}
        if p["middle"] and r.random() < 0.1:
            self.rows["PAT_ALIAS"].append({"ALIAS_ID": self.nid("AL"), "PAT_ID": pat_id,
                                           "ALIAS_NAME": f"{r.choice(V.LAST_NAMES).upper()},{first.upper()}", "ALIAS_TYPE": "MAIDEN"})
        if reg > self.cfg.as_of - timedelta(days=730):
            self.adt("A04", pat_id)
        if self.chance("a08_update"):
            self.adt("A08", pat_id)
        return pat_id

    def pick_conditions(self, age: int) -> list[str]:
        pool = list(V.ICD10)
        if age < 18:
            pool = ["J45.909", "F41.1", "G43.909", "N39.0", "E66.9"]
        return self.r.sample(pool, k=min(len(pool), self.r.choice([0, 1, 1, 2, 3, 4, 5])))

    def pick_allergies(self) -> list[str]:
        if self.r.random() > 0.35:
            return []
        return self.r.sample(list(V.ALLERGENS), k=self.r.choice([1, 1, 2, 3]))

    # ------------------------------------------------------------- chart
    def gen_chart(self, pat_id: str, p: dict[str, Any], fac: str, conditions: list[str], allergies: list[str],
                  primary: bool, light: bool = False) -> None:
        r, meta = self.r, self._pat_meta[pat_id]
        start = meta["reg"]
        end = p["deceased"] or self.cfg.as_of
        visits = [self.gen_visit(pat_id, fac, start, end) for _ in range(r.randint(1, 3 if light else 12))]
        visits.sort(key=lambda v: v["ADMIT_DT"])
        for code in conditions:
            self.gen_dx(pat_id, code, r.choice(visits), start)
        if not light and self.chance("free_text_dx"):
            dx_id = self.nid("DX")
            self.rows["DX"].append({"DX_ID": dx_id, "PAT_ID": pat_id, "VISIT_ID": "", "CODE": "", "CODE_TYPE": "",
                                    "DX_DESC": r.choice(V.FREE_TEXT_DX), "STATUS": "A", "ONSET_DT": "", "RESOLVED_DT": ""})
            self.plant("free_text_dx", "DX", dx_id)
        if not light and self.chance("local_dx"):
            code = r.choice(list(V.LOCAL_DX))
            dx_id = self.nid("DX")
            self.rows["DX"].append({"DX_ID": dx_id, "PAT_ID": pat_id, "VISIT_ID": "", "CODE": code, "CODE_TYPE": "L",
                                    "DX_DESC": V.LOCAL_DX[code][0], "STATUS": r.choice("AI"), "ONSET_DT": d8(start), "RESOLVED_DT": ""})
            self.truth["dx"][dx_id] = V.LOCAL_DX[code][1]
            self.plant("local_dx_code", "DX", dx_id, code=code)
        self.gen_meds(pat_id, conditions, visits)
        for a in allergies:
            self.gen_allergy(pat_id, a, start)
        if allergies and self.chance("nka_row"):
            alg = self.nid("ALG")
            self.rows["ALLERGY"].append({"ALG_ID": alg, "PAT_ID": pat_id, "ALLERGEN": "NKA", "REACTION": "",
                                         "SEVERITY": "", "ENTERED_DT": d8(start)})
            self.plant("nka_conflict", "ALLERGY", alg, reason="NKA row alongside allergies")
        for v in visits:
            if v["STATUS"] != "C":
                continue
            vt = v["VISIT_TYPE"]
            if vt in ("OV", "OVN", "ER", "IP", "OBS"):
                self.gen_vitals(pat_id, v, fac)
                if r.random() < 0.5:
                    self.gen_labs(pat_id, v)
            if r.random() < 0.5:
                self.gen_note(pat_id, v)
            self.gen_charges(pat_id, v)
        if primary:
            self.gen_immunizations(pat_id, p, start, end)
        self.gen_sched(pat_id, fac, start, end)

    def gen_visit(self, pat_id: str, fac: str, start: date, end: date) -> dict[str, str]:
        r = self.r
        vtypes = list(V.VISIT_TYPES)
        vt = r.choices(vtypes, weights=[V.VISIT_TYPES[k][1] for k in vtypes])[0]
        vid = self.nid("V", 7)
        if vt == "XX" or self.chance("visit_xx"):
            vt = "XX"
            self.plant("unknown_visit_type", "VISIT", vid)
        admit = self.rand_dt(start, end, (0, 23) if vt in ("ER", "IP") else (7, 18))
        lo, hi = max(start.year, 2009), min(end.year, self.cfg.as_of.year) - 1
        if self.chance("dst_ambiguous") and lo <= hi:
            d = first_sunday_nov(r.randint(lo, hi))
            admit = datetime(d.year, d.month, d.day, 1, 30)
            self.plant("dst_ambiguous_time", "VISIT", vid)
        disch = ""
        status = "X" if r.random() < 0.04 else "C"
        if vt in ("IP", "OBS") and status == "C":
            disch = dt12(admit + timedelta(hours=r.randint(20, 24 * 7)))
            if vt == "IP" and self.chance("missing_discharge"):
                disch = ""
                self.plant("missing_discharge", "VISIT", vid)
        clinics = [d[0] for d in V.DEPTS if d[1] == fac and d[3] == "clinic"] or ["D200"]
        dept = {"ER": "D100", "IP": "D110", "OBS": "D110", "TEL": "D910"}.get(vt, r.choice(clinics))
        prov = r.choice(self.providers)["PROV_ID"]
        if self.chance("orphan_provider"):
            prov = "PR999"
            self.plant("orphan_provider", "VISIT", vid)
        row = {"VISIT_ID": vid, "PAT_ID": pat_id, "VISIT_TYPE": vt, "ADMIT_DT": dt12(admit), "DISCH_DT": disch,
               "DEPT_ID": dept, "ATTEND_PROV_ID": prov, "REASON_TEXT": r.choice(["f/u", "ANNUAL", "cough", "chest pain", "med refill", "fall", ""]),
               "STATUS": status}
        self.rows["VISIT"].append(row)
        return row

    def gen_dx(self, pat_id: str, icd10: str, visit: dict[str, str], start: date) -> None:
        r = self.r
        dx_id = self.nid("DX")
        onset = self.rand_date(start - timedelta(days=3650), start)
        icd9 = next((k for k, (_, targets) in V.ICD9.items() if targets[0] == icd10), None)
        code, ctype, desc = icd10, "10", V.ICD10[icd10]
        if icd9 and onset < ICD10_CUTOVER:
            code, ctype, desc = icd9, "9", V.ICD9[icd9][0]
            if len(V.ICD9[icd9][1]) > 1:
                self.plant("icd9_one_to_many", "DX", dx_id, code=icd9)
            if r.random() < 0.15:
                ctype = ""
                self.plant("missing_code_type", "DX", dx_id)
        elif icd10 == "M54.50" and self.chance("retired_icd10"):
            code = "M54.5"
            self.plant("retired_code", "DX", dx_id, code=code)
        status = r.choices(["A", "I", "R", ""], weights=[70, 10, 15, 5])[0]
        self.rows["DX"].append({"DX_ID": dx_id, "PAT_ID": pat_id, "VISIT_ID": visit["VISIT_ID"], "CODE": code,
                                "CODE_TYPE": ctype, "DX_DESC": desc.upper(), "STATUS": status, "ONSET_DT": d8(onset),
                                "RESOLVED_DT": d8(self.rand_date(onset, self.cfg.as_of)) if status == "R" else ""})
        self.truth["dx"][dx_id] = icd10

    def gen_meds(self, pat_id: str, conditions: list[str], visits: list[dict[str, str]]) -> None:
        r = self.r
        chronic = {"E11.9": ["HFORM0002", "HFORM0005"], "I10": ["HFORM0001"], "E78.5": ["HFORM0003"],
                   "I48.91": ["HFORM0004", "HFORM0011"], "E03.9": ["HFORM0008"], "K21.9": ["HFORM0009"],
                   "F32.A": ["HFORM0012"], "J45.909": ["HFORM0007"], "Z79.01": ["HFORM0004"]}
        codes = [r.choice(chronic[c]) for c in conditions if c in chronic]
        acute = ["HFORM0006", "HFORM0010", "HFORM0013", "HFORM0014", "HFORM0015", "HFORM0099"]
        codes += [r.choices(acute, weights=[30, 15, 30, 20, 3, 2])[0] for _ in range(r.choice([0, 0, 1, 2]))]
        for code in codes:
            name, rx, doses, sigs, flag = V.FORMULARY[code]
            v = r.choice(visits)
            start = datetime.strptime(v["ADMIT_DT"][:8], "%Y%m%d").date()
            acute = code in ("HFORM0006", "HFORM0010", "HFORM0013", "HFORM0014", "HFORM0015", "HFORM0099")
            status = "C" if acute else r.choices(["A", "D"], weights=[85, 15])[0]
            oid = self.nid("ORD")
            self.rows["MED_ORD"].append({
                "ORD_ID": oid, "PAT_ID": pat_id, "VISIT_ID": v["VISIT_ID"], "PROV_ID": v["ATTEND_PROV_ID"],
                "FORM_CODE": code, "DRUG_NAME": name, "DOSE": r.choice(doses), "SIG": r.choice(sigs),
                "START_DT": d8(start), "STOP_DT": d8(start + timedelta(days=10)) if acute else "", "STATUS": status})
            if rx is None:
                self.plant("unmappable_medication", "MED_ORD", oid, code=code)
            if flag and status == "A":
                self.truth["sentinel"].setdefault(f"active_{flag}", []).append(oid)

    def gen_allergy(self, pat_id: str, allergen: str, start: date) -> None:
        r = self.r
        alg = self.nid("ALG")
        reacts = r.sample(list(V.REACTIONS), k=r.choice([0, 1, 1, 2]))
        sev = r.choice(["MILD", "MOD", "SEV", ""])
        self.rows["ALLERGY"].append({"ALG_ID": alg, "PAT_ID": pat_id, "ALLERGEN": allergen,
                                     "REACTION": ";".join(reacts) if r.random() < 0.9 else "unknown",
                                     "SEVERITY": sev, "ENTERED_DT": d8(self.rand_date(start, self.cfg.as_of))})
        if V.ALLERGENS[allergen] is None:
            self.plant("uncodable_allergen", "ALLERGY", alg, allergen=allergen)
        self.truth["allergy"][alg] = V.ALLERGENS[allergen]

    def gen_labs(self, pat_id: str, v: dict[str, str]) -> None:
        r = self.r
        meta = self._pat_meta[pat_id]
        acc = self.nid("A", 8)
        collect = datetime.strptime(v["ADMIT_DT"], "%Y%m%d%H%M") + timedelta(minutes=r.randint(10, 90))
        recent = collect.date() > self.cfg.as_of - timedelta(days=30)
        tests = r.sample([c for c in V.LABS if c != "XLAB7"], k=r.randint(1, 6))
        if r.random() < 0.03:
            tests.append("XLAB7")
        obx = []
        for code in tests:
            desc, loinc, unit, kind, normal, typical = V.LABS[code]
            res_id = self.nid("R", 7)
            flag, ref = "", ""
            if kind == "num":
                val = round(r.uniform(*typical), 1 if typical[1] < 50 else 0)
                sval = f"{val:g}"
                ref = f"{normal[0]:g}-{normal[1]:g}" if normal[0] > 0 else f"<{normal[1]:g}"
                flag = "H" if val > normal[1] else "L" if val < normal[0] else ""
                if self.chance("lab_comparator"):
                    sval = r.choice([f"<{normal[0]:g}", f">{typical[1]:g}"])
                    self.plant("lab_comparator_value", "LAB_RESULT", res_id, value=sval)
                elif self.chance("lab_text"):
                    sval = r.choice(["see note", "hemolyzed", "QNS"])
                    flag = ""
                    self.plant("lab_text_value", "LAB_RESULT", res_id, value=sval)
            elif kind == "coded":
                sval = r.choice(["NEG", "NEG", "POS", "TRACE"] if code == "UAPROT" else ["NEG", "NEG", "POS"])
                flag = "A" if sval in ("POS", "TRACE") else ""
            else:
                sval = r.choice(["Result faxed to provider", "Pending review", "ABNORMAL - CALL LAB"])
                self.plant("unmappable_lab", "LAB_RESULT", res_id, code=code)
            out_unit = unit.upper() if unit and r.random() < 0.3 else unit
            row = {"RES_ID": res_id, "PAT_ID": pat_id, "VISIT_ID": v["VISIT_ID"], "ACCESSION": acc, "TEST_CODE": code,
                   "TEST_NAME": desc, "RESULT_VAL": sval, "UNITS": out_unit, "REF_RANGE": ref, "ABN_FLAG": flag,
                   "COLLECT_DT": dt12(collect)}
            status = "F"
            if recent:
                self.plant("feed_only_lab", "LAB_RESULT", f"{acc}:{code}")
            else:
                self.rows["LAB_RESULT"].append(row)
            if recent or r.random() < 0.2:
                if not recent and kind == "num" and self.chance("oru_corrected") and sval.replace(".", "").isdigit():
                    sval = f"{float(sval) * 1.1:.1f}"
                    status = "C"
                    self.plant("oru_corrected_result", "LAB_RESULT", res_id, corrected_value=sval)
                obx.append((code, desc, sval, out_unit, ref, flag, status, collect))
        if obx:
            self.oru(pat_id, meta, acc, obx)

    def gen_vitals(self, pat_id: str, v: dict[str, str], fac: str) -> None:
        r = self.r
        _, _, _, wt_u, temp_u, ht_u = next(f for f in V.FACILITIES if f[0] == fac)
        vid = self.nid("VT", 7)
        kg = r.uniform(12, 130)
        sbp, dbp = r.randint(95, 175), r.randint(55, 105)
        temp_c = round(r.uniform(36.1, 38.6), 1)
        wt = f"{kg * 2.20462:.1f}" if wt_u == "lb" else f"{kg:.1f}"
        temp = f"{temp_c * 9 / 5 + 32:.1f}" if temp_u == "F" else f"{temp_c:.1f}"
        cm = r.uniform(100, 195)
        ht = f"{cm / 2.54:.0f}" if ht_u == "in" else f"{cm:.0f}"
        bp = f"{sbp}/{dbp}"
        if self.chance("vital_weight_typo"):
            wt = f"{float(wt) * 10:.0f}"
            self.plant("implausible_vital", "VITALS", vid, field="WT", value=wt)
        if self.chance("vital_temp_nodecimal"):
            temp = temp.replace(".", "")
            self.plant("implausible_vital", "VITALS", vid, field="TEMP", value=temp)
        if self.chance("vital_bp_malformed"):
            bp = f"{sbp}/"
            self.plant("malformed_vital", "VITALS", vid, field="BP", value=bp)
        if self.chance("vital_unit_in_value"):
            wt = f"{wt} {'lbs' if wt_u == 'lb' else 'kg'}"
        self.rows["VITALS"].append({"VITAL_ID": vid, "PAT_ID": pat_id, "VISIT_ID": v["VISIT_ID"],
                                    "TAKEN_DT": v["ADMIT_DT"], "BP": bp, "PULSE": str(r.randint(50, 120)),
                                    "RESP": str(r.randint(10, 24)), "TEMP": temp, "WT": wt, "HT": ht if r.random() < 0.6 else "",
                                    "SPO2": str(r.randint(90, 100))})

    def gen_note(self, pat_id: str, v: dict[str, str]) -> None:
        r = self.r
        nid = self.nid("N", 7)
        ntype = {"IP": "DS", "OBS": "HP", "TEL": "TEL"}.get(v["VISIT_TYPE"], "PN")
        body = (r"{\rtf1\ansi {\b SUBJECTIVE:}\par " + f"Patient seen for {v['REASON_TEXT'] or 'visit'}. "
                + r"Reports feeling {\i somewhat} better.\par {\b ASSESSMENT/PLAN:}\par Continue current meds.\par}")
        if self.chance("note_truncated"):
            body = (body[:-1] + " " + "Detailed history follows. " * 4000)[:65535]
            self.plant("truncated_note", "NOTE", nid)
        self.rows["NOTE"].append({"NOTE_ID": nid, "PAT_ID": pat_id, "VISIT_ID": v["VISIT_ID"],
                                  "AUTHOR_PROV_ID": v["ATTEND_PROV_ID"], "NOTE_TYPE": ntype,
                                  "NOTE_DT": v["ADMIT_DT"], "NOTE_TEXT": body})

    def gen_charges(self, pat_id: str, v: dict[str, str]) -> None:
        r = self.r
        vt = v["VISIT_TYPE"]
        if vt == "TEL":
            return
        codes = {"ER": ["99284", "93000", "HC1002", "HC1003"], "IP": ["99221", "80053", "85025"],
                 "OBS": ["99221", "80053"]}.get(vt, ["99212", "99213", "99214", "99203", "G0438", "83036", "36415", "HC1001"])
        post = datetime.strptime(v["ADMIT_DT"][:8], "%Y%m%d").date() + timedelta(days=r.randint(0, 5))
        picks = r.sample(codes, k=min(len(codes), r.randint(1, 3)))
        if r.random() < 0.02:
            picks.append("HC9999")
        for code in picks:
            cid = self.nid("C", 7)
            price = V.CHARGES[code][2]
            amount = f"{price:.2f}" if post < date(2012, 1, 1) else str(price * 100)
            mods = r.choice(["", "", "", "", "25", "25 59", "LT"])
            self.rows["CHARGE"].append({"CHG_ID": cid, "PAT_ID": pat_id, "VISIT_ID": v["VISIT_ID"], "CHG_CODE": code,
                                        "MODIFIERS": mods, "UNITS": "1", "AMOUNT": amount, "POST_DT": d8(post)})
            if V.CHARGES[code][1] is None:
                self.plant("unmappable_charge", "CHARGE", cid, code=code)

    def gen_immunizations(self, pat_id: str, p: dict[str, Any], start: date, end: date) -> None:
        r = self.r
        meta = self._pat_meta[pat_id]
        for _ in range(r.choice([0, 1, 2, 3, 5])):
            code = r.choice([c for c in V.VACCINES if c != "PPD"]) if r.random() > 0.03 else "PPD"
            iid = self.nid("IM")
            d = self.rand_date(start, end)
            self.rows["IMMUN"].append({"IMM_ID": iid, "PAT_ID": pat_id, "VACCINE_CODE": code, "VACCINE_NAME": V.VACCINES[code][0],
                                       "ADMIN_DT": d8(d), "LOT": f"L{r.randint(1000, 99999)}", "GIVEN_BY": ""})
            if V.VACCINES[code][1] is None:
                self.plant("not_a_vaccine", "IMMUN", iid, code=code)
            if r.random() < 0.7 and V.VACCINES[code][1]:
                reg_date = d
                if self.chance("immun_date_conflict"):
                    reg_date = d + timedelta(days=r.choice([-1, 1, 30]))
                    self.plant("immun_date_conflict", "IMMUN", iid, registry_date=reg_date.isoformat())
                self.registry_row(meta, p, V.VACCINES[code][1], V.VACCINES[code][0], reg_date)
        if self.chance("registry_only"):
            cvx = r.choice(["140", "115", "208", "187"])
            d = self.rand_date(start, end)
            self.registry_row(meta, p, cvx, "REGISTRY REPORTED", d)
            self.plant("registry_only_immunization", "registry", f"{meta['row']['MRN']}:{cvx}:{d.isoformat()}")

    def registry_row(self, meta: dict[str, Any], p: dict[str, Any], cvx: str, name: str, d: date) -> None:
        self.registry.append([meta["row"]["MRN"], meta["fac"], p["last"].upper(), p["first"].upper(),
                              p["dob"].strftime("%m/%d/%Y"), cvx, name, d.strftime("%m/%d/%Y"), f"L{self.r.randint(1000, 99999)}"])

    def gen_sched(self, pat_id: str, fac: str, start: date, end: date) -> None:
        r = self.r
        for _ in range(r.choice([0, 1, 2, 4])):
            aid = self.nid("AP")
            future = r.random() < 0.3 and end == self.cfg.as_of
            when = self.rand_dt(self.cfg.as_of + timedelta(days=1), self.cfg.as_of + timedelta(days=120)) if future \
                else self.rand_dt(start, end)
            status = "S" if future else r.choices(["C", "N", "X", "B", "A"], weights=[70, 10, 10, 5, 1])[0]
            prov = r.choice(self.providers)["PROV_ID"]
            clinics = [d[0] for d in V.DEPTS if d[1] == fac and d[3] == "clinic"] or ["D200"]
            row = {"APPT_ID": aid, "PAT_ID": pat_id, "PROV_ID": prov, "DEPT_ID": r.choice(clinics),
                   "APPT_DT": dt12(when), "DURATION_MIN": r.choice(["15", "20", "30", "40", "60"]),
                   "STATUS": status, "REASON": r.choice(["F/U", "PHYSICAL", "NEW PT", "MED CHECK", ""])}
            self.rows["SCHED"].append(row)
            self.truth["appt_status"][aid] = V.APPT_STATUS[status]
            if status == "B":
                self.plant("unrepresentable_status", "SCHED", aid, status="B")
            if future and r.random() < 0.3:
                self.siu("S12", pat_id, row)
                if self.chance("siu_cancel"):
                    self.siu("S15", pat_id, row)
                    self.truth["appt_status"][aid] = "cancelled"
                    self.plant("siu_newer_status", "SCHED", aid)

    def gen_coverage(self, pat_id: str, p: dict[str, Any]) -> None:
        r = self.r
        if r.random() > 0.85:
            return
        age = (self.cfg.as_of - p["dob"]).days // 365
        plans = ["PL03"] if age >= 65 else [r.choice(["PL01", "PL02", "PL04"])]
        if r.random() < 0.2:
            plans.append(r.choice([pl for pl in ("PL01", "PL02", "PL04", "PL05") if pl not in plans]))
        for i, plan in enumerate(plans, start=1):
            cid = self.nid("COV")
            order = str(i)
            if i == 2 and self.chance("cob_duplicate"):
                order = "1"
                self.plant("cob_duplicate", "COVERAGE", cid)
            rel = "19" if age < 18 else r.choice(["18", "18", "18", "01", "G8", ""])
            self.rows["COVERAGE"].append({"COV_ID": cid, "PAT_ID": pat_id, "PLAN_ID": plan,
                                          "MEMBER_ID": f"M{r.randint(10**8, 10**9 - 1)}", "REL_CODE": rel, "COB_ORDER": order,
                                          "EFF_DT": d8(self.rand_date(date(2015, 1, 1), self.cfg.as_of)), "TERM_DT": ""})
            if rel == "":
                self.plant("missing_relationship", "COVERAGE", cid)

    # ------------------------------------------------------------- HL7 v2
    def _msh(self, mtype: str, when: datetime) -> str:
        self._msg += 1
        return f"MSH|^~\\&|HALCYON|RIVERBEND|BRIDGE|NIMBUS|{dt12(when)}||{mtype}|MSG{self._msg:07d}|P|2.3"

    @staticmethod
    def esc(s: str) -> str:
        return s.replace("\\", "\\E\\").replace("|", "\\F\\").replace("^", "\\S\\").replace("~", "\\R\\").replace("&", "\\T\\")

    def _pid(self, pat_id: str, override: dict[str, str] | None = None) -> str:
        row = dict(self._pat_meta[pat_id]["row"])
        row.update(override or {})
        last, _, rest = row["PAT_NAME"].partition(",")
        first, _, middle = rest.partition(" ")
        addr = row["ADDR"].split("^") if "^" in row["ADDR"] else [row["ADDR"], "", "", "", ""]
        e = self.esc
        return (f"PID|1||{row['MRN']}^^^{row['FAC_ID']}^MR||{e(last)}^{e(first)}^{e(middle)}||{row['DOB']}|{row['SEX']}|||"
                f"{e(addr[0])}^{e(addr[1])}^{e(addr[2])}^{e(addr[3])}^{e(addr[4])}||{e(row['PHONE_HOME'])}|||||||{row['SSN4']}")

    def adt(self, event: str, pat_id: str, merge_into: str | None = None) -> None:
        meta = self._pat_meta[pat_id]
        when = datetime.combine(meta["reg"], datetime.min.time()) + timedelta(hours=9)
        segs = [self._msh(f"ADT^{event}", when), f"EVN|{event}|{dt12(when)}"]
        if event == "A08":
            r = self.r
            p = meta["person"]
            city, state, zip3 = r.choice(V.CITIES)
            new_addr = f"{r.randint(10, 9999)} {r.choice(V.STREETS)}^^{city}^{state}^{zip3}{r.randint(10, 99)}"
            new_phone, e164 = self.phone()
            when = datetime.combine(min(self.cfg.as_of, meta["reg"] + timedelta(days=r.randint(30, 900))), datetime.min.time()) + timedelta(hours=10)
            segs = [self._msh("ADT^A08", when), f"EVN|A08|{dt12(when)}"]
            segs.append(self._pid(pat_id, {"ADDR": new_addr, "PHONE_HOME": new_phone}))
            self.truth["a08_demographics"][pat_id] = {"addr": new_addr, "phone": e164}
            self.plant("a08_newer_demographics", "PAT", pat_id)
            _ = p
        elif event == "A40":
            target = self._pat_meta[merge_into]["row"]
            dup = meta["row"]
            when = datetime.combine(self.cfg.as_of - timedelta(days=self.r.randint(1, 200)), datetime.min.time()) + timedelta(hours=11)
            segs = [self._msh("ADT^A40", when), f"EVN|A40|{dt12(when)}", self._pid(merge_into),
                    f"MRG|{dup['MRN']}^^^{dup['FAC_ID']}^MR"]
        else:
            segs.append(self._pid(pat_id))
        segs.append(f"PV1|1|O|{meta['fac']}")
        self.feeds["adt"].append("\r".join(segs))

    def oru(self, pat_id: str, meta: dict[str, Any], acc: str, obx: list[tuple]) -> None:
        when = obx[0][7] + timedelta(hours=2)
        segs = [self._msh("ORU^R01", when), self._pid(pat_id), f"OBR|1||{acc}|PANEL^LAB PANEL^L|||{dt12(obx[0][7])}"]
        for i, (code, desc, val, unit, ref, flag, status, collect) in enumerate(obx, 1):
            vtype = "NM" if val.replace(".", "", 1).isdigit() else "ST"
            segs.append(f"OBX|{i}|{vtype}|{code}^{self.esc(desc)}^L||{self.esc(val)}|{self.esc(unit)}|{ref}|{flag}|||{status}|||{dt12(collect)}")
        self.feeds["oru"].append("\r".join(segs))

    def siu(self, event: str, pat_id: str, appt: dict[str, str]) -> None:
        when = datetime.strptime(appt["APPT_DT"], "%Y%m%d%H%M") - timedelta(days=self.r.randint(1, 20) if event == "S15" else 30)
        status = "Booked" if event == "S12" else "Cancelled"
        segs = [self._msh(f"SIU^{event}", min(when, datetime.combine(self.cfg.as_of, datetime.min.time()))),
                f"SCH|{appt['APPT_ID']}||||||{appt['REASON']}||||^^{appt['DURATION_MIN']}^{appt['APPT_DT']}|||||||||||||{status}",
                self._pid(pat_id), f"AIP|1||{appt['PROV_ID']}", f"AIL|1||{appt['DEPT_ID']}"]
        self.feeds["siu"].append("\r".join(segs))

    # ------------------------------------------------------------- output
    def write(self, out: Path) -> dict[str, Any]:
        db_path = out / "halcyon.db"
        if db_path.exists():
            db_path.unlink()
        con = sqlite3.connect(db_path)
        con.executescript((Path(__file__).parent / "schema.sql").read_text())
        for table, rows in self.rows.items():
            if not rows:
                continue
            cols = list(rows[0])
            con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            [tuple(r[c] for c in cols) for r in rows])
        con.commit()
        con.close()

        feeds = out / "feeds"
        feeds.mkdir(exist_ok=True)
        for kind, msgs in self.feeds.items():
            (feeds / f"{kind}_0001.hl7").write_bytes("\n\n".join(msgs).encode("latin-1", errors="replace") + b"\n")

        ext = out / "extracts"
        ext.mkdir(exist_ok=True)
        with open(ext / "immunizations.csv", "w", encoding="latin-1", errors="replace", newline="") as f:
            w = csv.writer(f, delimiter="|")
            w.writerow(["MRN", "FAC", "LAST", "FIRST", "DOB", "CVX", "VACCINE", "ADMIN_DATE", "LOT"])
            w.writerows(self.registry)
        with open(ext / "charge_master.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["CHG_CODE", "DESCRIPTION", "CPT_HCPCS", "PRICE"])
            for code, (desc, cpt, price) in V.CHARGES.items():
                w.writerow([code, desc, cpt or "", f"{price:.2f}"])

        key = out / "answer_key"
        key.mkdir(exist_ok=True)
        with open(key / "issues.jsonl", "w") as f:
            for issue in self.issues:
                f.write(json.dumps(issue) + "\n")
        (key / "persons.json").write_text(json.dumps(self.persons, indent=1))
        (key / "truth.json").write_text(json.dumps(self.truth, indent=1, default=str))

        counts = {t: len(rs) for t, rs in sorted(self.rows.items())}
        counts.update({f"feed_{k}": len(v) for k, v in self.feeds.items()}, registry_rows=len(self.registry))
        issue_counts: dict[str, int] = defaultdict(int)
        for i in self.issues:
            issue_counts[i["type"]] += 1
        manifest = {"system": "Halcyon Classic", "generatorVersion": GENERATOR_VERSION, "seed": self.cfg.seed,
                    "patients": self.cfg.patients, "asOf": self.cfg.as_of.isoformat(), "counts": counts,
                    "notes": {
                        "timestamps": "Facility local time, no offset. FAC1/FAC2 US Central, FAC3 US Mountain.",
                        "units": "VITALS have no unit columns; FAC1/FAC2 record lb/degF/in, FAC3 kg/degC/cm.",
                        "charges": "AMOUNT is dollars (with decimals) before 2012-01-01, integer cents after.",
                        "feeds": "HL7 v2.3. ADT A08 newer than PAT; A40 = merge (MRG = retired MRN). ORU: last 30 days only in feed.",
                    }}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
        return {"counts": counts, "issues": dict(issue_counts)}


def generate(out: Path | str, seed: int = 42, patients: int = 500, as_of: date | None = None) -> dict[str, Any]:
    cfg = Config(seed=seed, patients=patients)
    if as_of:
        cfg.as_of = as_of
    return Generator(cfg).run(Path(out))
