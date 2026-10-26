"""Meridian MCS/2 synthetic export generator (test-only; Bridge never imports this).

Writes pipe-delimited extract files with a header row (latin-1, CRLF), the vendor's extract guide
and the site's kickoff memo (the documentary estate), a manifest, and ``answer_key/`` (ground truth
in the Halcyon answer-key shapes so ``testbed/scoring.py`` works, plus the estate grading ledger).
Deterministic per seed.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import estate, vocab as V

MIGRATION = date(2016, 3, 1)  # Sun Ridge moved onto MCS/2; its history was loaded as-is

FILES = {
    "CAMPUS": ["CAMPUS_CD", "CAMPUS_NAME", "CITY", "STATE"],
    "CLINIC": ["CLINIC_CD", "CLINIC_NAME", "CAMPUS_CD"],
    "STAFF": ["STAFF_ID", "STAFF_NAME", "ROLE", "SPEC_TXT", "NPI", "BILLS_YN", "ACTIVE_YN", "TERM_DATE"],
    "CARRIER": ["CARRIER_CD", "CARRIER_NAME"],
    "INSPLAN": ["PLAN_CD", "CARRIER_CD", "PLAN_NAME", "PLAN_TYPE"],
    "PERSON": ["PERSON_NO", "MRN", "CAMPUS_CD", "LAST_NM", "FIRST_NM", "MID_NM", "BIRTH_DT", "SEX_CD", "SSN_LAST4",
               "RACE_TXT", "ADDR1", "ADDR2", "CITY", "ST", "ZIP", "HOME_PH", "CELL_PH", "DECEASED_DT", "NKA_YN",
               "UPDATED_DT"],
    "INSCOV": ["COV_NO", "PERSON_NO", "PLAN_CD", "MEMBER_ID", "REL_CD", "PRIORITY", "EFF_DT", "END_DT"],
    "VISIT": ["VISIT_NO", "PERSON_NO", "CLINIC_CD", "VISIT_TYPE", "ADMIT_TS", "DISCH_TS", "STATUS", "ATTEND_ID",
              "CHIEF_COMPLAINT"],
    "PROBLEM": ["PROB_NO", "PERSON_NO", "VISIT_NO", "DX_CODE", "CODE_SYS", "DX_TEXT", "ONSET_DT", "RESOLVE_DT",
                "STATUS"],
    "ALLERGY": ["ALG_NO", "PERSON_NO", "ALLERGEN_TXT", "REACTION_TXT", "SEVERITY", "NOTED_DT"],
    "DRUGFILE": ["DRUG_CD", "DRUG_DESC", "RXNORM"],
    "RXORDER": ["RX_NO", "PERSON_NO", "VISIT_NO", "DRUG_CD", "DRUG_DESC", "DOSE_TXT", "SIG_TXT", "ORDER_DT", "STOP_DT",
                "RX_STATUS", "PRESCRIBER_ID"],
    "TESTDICT": ["TEST_CD", "TEST_NAME", "LOINC", "UNITS"],
    "LABRES": ["RES_NO", "PERSON_NO", "VISIT_NO", "ACCESSION", "TEST_CD", "RESULT", "UNITS", "REF_RANGE", "ABN",
               "COLLECTED_TS", "RESULT_STATUS"],
    "VITALS": ["VS_NO", "PERSON_NO", "VISIT_NO", "TAKEN_TS", "VS_TYPE", "VS_VALUE", "VS_UNIT"],
    "APPT": ["APPT_NO", "PERSON_NO", "CLINIC_CD", "APPT_TS", "LEN_MIN", "APPT_STATUS", "PROVIDER_ID", "APPT_REASON"],
}


@dataclass
class Config:
    patients: int = 300
    seed: int = 42
    as_of: date = date(2026, 9, 30)
    rates: dict[str, float] = field(default_factory=lambda: {
        "cross_campus_duplicate": 0.12, "duplicate_registration": 0.04, "placeholder_dob": 0.02,
        "sex_x": 0.02, "missing_rel": 0.06, "missing_discharge": 0.10, "free_text_dx": 0.06,
        "nka_conflict": 0.03, "lab_corrected": 0.03, "lab_cancelled": 0.04, "implausible_vital": 0.01,
        "bumped_appt": 0.05,
    })


def _mdy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _oracle_ts(dt: datetime) -> str:
    return dt.strftime("%d-%b-%y %H:%M").upper()


def _npi(rng: random.Random) -> str:
    base = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(8)]
    total = 0
    for i, d in enumerate(reversed([8, 0, 8, 4, 0] + base)):
        d = d * 2 if i % 2 == 0 else d
        total += d - 9 if d > 9 else d
    return "".join(map(str, base)) + str((10 - total % 10) % 10)


class Gen:
    def __init__(self, cfg: Config):
        self.cfg, self.rng = cfg, random.Random(cfg.seed)
        self.rows: dict[str, list[dict[str, str]]] = {f: [] for f in FILES}
        self.persons: dict[str, list[str]] = {}
        self.truth: dict[str, Any] = {"person": {}, "dx": {}, "allergy": {}, "appt_status": {},
                                      "provider_specialty": {}, "visit_class": {}, "campus_tz": {},
                                      "vital_units": {}, "relationship": {}, "lab_cancelled": [],
                                      "sex_code": {}, "rxnorm": {}, "void_kind": {}, "vital_unit": {}}
        self.issues: list[dict[str, Any]] = []
        self.seq: dict[str, int] = {}

    def nid(self, kind: str, start: int) -> int:
        self.seq[kind] = self.seq.get(kind, start) + 1
        return self.seq[kind]

    def issue(self, typ: str, table: str, key: str, **extra: Any) -> None:
        self.issues.append({"type": typ, "table": table, "key": key, **extra})

    def rdate(self, lo: date, hi: date) -> date:
        return lo + timedelta(days=self.rng.randint(0, max(0, (hi - lo).days)))

    # ------------------------------------------------------------------ reference
    def reference(self) -> None:
        r = self.rng
        for code, (name, city, st, tz, units) in V.CAMPUSES.items():
            self.rows["CAMPUS"].append({"CAMPUS_CD": code, "CAMPUS_NAME": name, "CITY": city, "STATE": st})
            self.truth["campus_tz"][code] = tz
            self.truth["vital_units"][code] = units
        for code, (name, campus) in V.CLINICS.items():
            self.rows["CLINIC"].append({"CLINIC_CD": code, "CLINIC_NAME": name, "CAMPUS_CD": campus})
        for code, name in V.CARRIERS.items():
            self.rows["CARRIER"].append({"CARRIER_CD": code, "CARRIER_NAME": name})
        for code, (carrier, name, typ) in V.PLANS.items():
            self.rows["INSPLAN"].append({"PLAN_CD": code, "CARRIER_CD": carrier, "PLAN_NAME": name, "PLAN_TYPE": typ})
        specs = list(V.SPECIALTIES)
        for i in range(18):
            sid = f"ST{i + 1:04d}"
            spec = specs[i % len(specs)]
            role = {"FNP": "NP", "PA-C": "PA"}.get(spec, r.choice(["MD", "MD", "DO"]))
            sex_first = r.choice(V.FIRST_M + V.FIRST_F)
            npi, bills = _npi(r), "Y" if role in ("MD", "DO", "NP", "PA") else "N"
            if i in (5, 11):
                npi = ""
                self.issue("npi_missing_billing", "STAFF", sid)
            elif i == 14:
                npi = npi[:-1] + str((int(npi[-1]) + 3) % 10)
                self.issue("npi_invalid", "STAFF", sid)
            active = "N" if i == 16 else "Y"
            self.rows["STAFF"].append({
                "STAFF_ID": sid, "STAFF_NAME": f"{r.choice(V.LAST_NAMES)}, {sex_first} {r.choice('ABCDEJKLMRST')}",
                "ROLE": role, "SPEC_TXT": spec, "NPI": npi, "BILLS_YN": bills, "ACTIVE_YN": active,
                "TERM_DATE": _mdy(date(2024, 6, 30)) if active == "N" else ""})
            self.truth["provider_specialty"][sid] = V.SPECIALTIES[spec]
            if spec == "Gen Surg":
                self.issue("unmapped_specialty", "STAFF", sid)
        for code, (desc, rx, truth_rx, _, _) in V.DRUGS.items():
            self.rows["DRUGFILE"].append({"DRUG_CD": code, "DRUG_DESC": desc, "RXNORM": rx})
            self.truth["rxnorm"][code] = truth_rx
        for code, (name, loinc, _, unit, _, _, _) in V.TESTS.items():
            self.rows["TESTDICT"].append({"TEST_CD": code, "TEST_NAME": name, "LOINC": loinc, "UNITS": unit})

    # ------------------------------------------------------------------ people
    def person_rows(self) -> None:
        r, rates = self.rng, self.cfg.rates
        for i in range(self.cfg.patients):
            pid = f"PRS{i + 1:05d}"
            campus = "HVMC" if r.random() < 0.7 else "SRC"
            sex = r.choice("MF")
            x_marker = r.random() < rates["sex_x"]
            first = r.choice(V.FIRST_M if sex == "M" else V.FIRST_F)
            last = r.choice(V.LAST_NAMES)
            if r.random() < 0.03:
                last = "PEÑA"
            dob = self.rdate(date(1932, 1, 1), date(2024, 6, 30))
            city, st, zip3 = r.choice(V.CITIES[campus])
            person = {
                "first": first, "last": last, "mid": r.choice("ABCDEFGHJKLMNRST") if r.random() < 0.7 else "",
                "dob": dob, "sex": sex, "x": x_marker, "ssn4": f"{r.randint(0, 9999):04d}" if r.random() > 0.03 else "",
                "race": r.choice(list(V.RACE_TEXT)), "campus": campus,
                "addr": (f"{r.randint(100, 9999)} {r.choice(V.STREETS)}", r.choice(["", "", "APT " + str(r.randint(1, 40))]),
                         city, st, f"{zip3}{r.randint(10, 99)}"),
                "phone": f"({r.choice(['575', '520'])}) 555-{r.randint(1000, 9999)}",
                "cell": f"{r.choice(['575', '520'])}-555-{r.randint(1000, 9999)}" if r.random() < 0.6 else "",
                "deceased": _mdy(self.rdate(date(2018, 1, 1), date(2026, 6, 1))) if r.random() < 0.02 else "",
            }
            self.truth["person"][pid] = {"dob": dob.isoformat(), "campus": campus}
            charts = [self.chart(pid, person, campus, date(2016, 3, 1), self.cfg.as_of)]
            if r.random() < rates["cross_campus_duplicate"]:
                other = "SRC" if campus == "HVMC" else "HVMC"
                charts.append(self.chart(pid, person, other, date(2006, 1, 1), date(2015, 12, 31), variant=True))
                self.issue("cross_campus_duplicate", "PERSON", charts[-1])
            if r.random() < rates["duplicate_registration"]:
                charts.append(self.chart(pid, person, campus, date(2017, 1, 1), self.cfg.as_of, typo=True))
                self.issue("duplicate_registration", "PERSON", charts[-1])
            self.persons[pid] = charts
            self.clinical(pid, person, charts)

    def chart(self, pid: str, p: dict[str, Any], campus: str, lo: date, hi: date,
              variant: bool = False, typo: bool = False) -> str:
        r = self.rng
        pno = str(self.nid("person", 100000))
        mrn = f"M{self.nid('mrn', 20000000):08d}"
        first, last, dob, ssn4 = p["first"], p["last"], p["dob"], p["ssn4"]
        if variant:
            if r.random() < 0.35:
                first = V.NICK.get(first, first)
            if r.random() < 0.3:
                ssn4 = ""
            if r.random() < 0.1 and dob.day <= 12:
                dob = date(dob.year, dob.day, dob.month)
        if typo and len(last) > 4:
            k = r.randint(1, len(last) - 2)
            last = last[:k] + last[k + 1] + last[k] + last[k + 2:]
        updated = self.rdate(lo, hi)
        birth = _mdy(dob)
        if not variant and not typo and r.random() < self.cfg.rates["placeholder_dob"]:
            birth = "01/01/1900"
            self.issue("placeholder_dob", "PERSON", pno)
        sex_cd = {"M": "1", "F": "2"}[p["sex"]]
        if p["x"] and updated >= date(2021, 1, 1):
            sex_cd = "3"
            self.issue("sex_x_marker", "PERSON", pno)
        elif r.random() < 0.01:
            sex_cd = "9"
        self.truth["sex_code"][pno] = {"1": "male", "2": "female", "3": "x", "9": "unknown"}[sex_cd]
        a1, a2, city, st, zipc = p["addr"]
        self.rows["PERSON"].append({
            "PERSON_NO": pno, "MRN": mrn, "CAMPUS_CD": campus, "LAST_NM": last, "FIRST_NM": first, "MID_NM": p["mid"],
            "BIRTH_DT": birth, "SEX_CD": sex_cd, "SSN_LAST4": ssn4, "RACE_TXT": p["race"], "ADDR1": a1, "ADDR2": a2,
            "CITY": city, "ST": st, "ZIP": zipc, "HOME_PH": p["phone"], "CELL_PH": p["cell"],
            "DECEASED_DT": p["deceased"] if not variant else "", "NKA_YN": "", "UPDATED_DT": _mdy(updated)})
        return pno

    # ------------------------------------------------------------------ clinical
    def clinical(self, pid: str, p: dict[str, Any], charts: list[str]) -> None:
        r, rates = self.rng, self.cfg.rates
        primary = charts[0]
        # coverage
        for prio in range(1, r.choice([1, 1, 2]) + 1):
            plan = r.choice(list(V.PLANS))
            rel = r.choice(["S", "S", "S", "P", "C", "O"])
            age = (self.cfg.as_of - p["dob"]).days / 365.25
            if age < 18:
                rel = "C"
            cno = str(self.nid("cov", 500000))
            eff = self.rdate(date(2012, 1, 1), date(2025, 1, 1))
            if r.random() < rates["missing_rel"]:
                self.issue("missing_relationship", "INSCOV", cno)
                rel_out = ""
            elif rel == "C" and p["campus"] == "SRC" and eff < MIGRATION:
                rel_out = "D"  # old Sun Ridge desk convention (the guide's code), kept by the 2016 migration
            else:
                rel_out = rel
            self.truth["relationship"][cno] = {"S": "self", "P": "spouse", "C": "child", "O": "other"}[rel]
            self.rows["INSCOV"].append({
                "COV_NO": cno, "PERSON_NO": primary, "PLAN_CD": plan, "MEMBER_ID": f"{plan[:3]}{r.randint(10**7, 10**8 - 1)}",
                "REL_CD": rel_out, "PRIORITY": str(prio), "EFF_DT": _mdy(eff),
                "END_DT": ""})
        # visits (the duplicate charts carry their own history)
        visits: list[tuple[str, str, datetime, str]] = []
        for chart in charts:
            campus = next(row["CAMPUS_CD"] for row in self.rows["PERSON"] if row["PERSON_NO"] == chart)
            n = r.randint(1, 5) if chart == primary else r.randint(1, 2)
            for _ in range(n):
                visits.append(self.visit(chart, campus))
        # problems
        for _ in range(r.choice([0, 1, 1, 2, 3])):
            self.problem(primary, visits)
        # allergies
        has_allergy = r.random() < 0.3
        nka = "N"
        if has_allergy:
            for alg in r.sample(list(V.ALLERGENS), r.choice([1, 1, 2])):
                ano = str(self.nid("alg", 700000))
                self.rows["ALLERGY"].append({
                    "ALG_NO": ano, "PERSON_NO": primary, "ALLERGEN_TXT": alg, "REACTION_TXT": r.choice(V.REACTIONS),
                    "SEVERITY": r.choice(V.SEVERITY), "NOTED_DT": _mdy(self.rdate(date(2008, 1, 1), date(2026, 1, 1)))})
                self.truth["allergy"][ano] = list(V.ALLERGENS[alg]) if V.ALLERGENS[alg] else None
                if V.ALLERGENS[alg] is None:
                    self.issue("uncoded_allergen", "ALLERGY", ano)
            if r.random() < rates["nka_conflict"] / 0.3:
                nka = "Y"
                self.issue("nka_conflict", "PERSON", primary)
        elif r.random() < 0.5:
            nka = "Y"
            if r.random() < 0.3:
                ano = str(self.nid("alg", 700000))
                self.rows["ALLERGY"].append({"ALG_NO": ano, "PERSON_NO": primary, "ALLERGEN_TXT": "NKDA",
                                             "REACTION_TXT": "", "SEVERITY": "", "NOTED_DT": _mdy(self.rdate(date(2010, 1, 1), date(2026, 1, 1)))})
        for row in self.rows["PERSON"]:
            if row["PERSON_NO"] == primary:
                row["NKA_YN"] = nka
        # medications
        for _ in range(r.choice([0, 1, 1, 2, 3])):
            code = r.choice(list(V.DRUGS))
            desc, rx, truth_rx, doses, sigs = V.DRUGS[code]
            start = self.rdate(date(2012, 1, 1), date(2026, 8, 1))
            status = r.choice(["ACTIVE", "ACTIVE", "DISCONTINUED", "COMPLETED", "HOLD"])
            rno = str(self.nid("rx", 300000))
            vis = r.choice(visits) if visits and r.random() < 0.5 else None
            self.rows["RXORDER"].append({
                "RX_NO": rno, "PERSON_NO": primary, "VISIT_NO": vis[0] if vis and vis[1] == primary else "",
                "DRUG_CD": code, "DRUG_DESC": desc, "DOSE_TXT": r.choice(doses), "SIG_TXT": r.choice(sigs),
                "ORDER_DT": _mdy(start), "STOP_DT": _mdy(start + timedelta(days=r.randint(10, 400))) if status in ("DISCONTINUED", "COMPLETED") else "",
                "RX_STATUS": status, "PRESCRIBER_ID": f"ST{r.randint(1, 18):04d}"})
            if truth_rx is None:
                self.issue("unmapped_medication", "RXORDER", rno)
        # appointments
        for _ in range(r.choice([0, 1, 2, 3])):
            clinic = r.choice([c for c, (_, camp) in V.CLINICS.items() if camp == p["campus"] and c not in ("HV3W", "HVED")])
            when = datetime.combine(self.rdate(date(2019, 1, 1), date(2026, 12, 15)), datetime.min.time()) \
                + timedelta(hours=r.randint(7, 16), minutes=r.choice([0, 15, 30, 45]))
            st = r.choice(["SCH", "ARR", "CMP", "CMP", "NOS", "CAN"])
            if r.random() < rates["bumped_appt"]:
                st = "BMP"
            ano = str(self.nid("appt", 900000))
            self.rows["APPT"].append({
                "APPT_NO": ano, "PERSON_NO": primary, "CLINIC_CD": clinic, "APPT_TS": _ts(when),
                "LEN_MIN": str(r.choice([15, 20, 30, 40, 60])), "APPT_STATUS": st,
                "PROVIDER_ID": f"ST{r.randint(1, 18):04d}", "APPT_REASON": r.choice(["FOLLOW UP", "ANNUAL", "SICK VISIT", ""])})
            self.truth["appt_status"][ano] = V.APPT_STATUS[st]
            if st == "BMP":
                self.issue("bumped_appointment", "APPT", ano)

    def visit(self, chart: str, campus: str) -> tuple[str, str, datetime, str]:
        r, rates = self.rng, self.cfg.rates
        choices = [(vt, cl) for vt, (_, clinics, _) in V.VISIT_TYPES.items() for cl in clinics
                   if V.CLINICS[cl][1] == campus]
        vt, clinic = r.choice(choices)
        lo = date(2020, 4, 1) if vt == "TH" else date(2010, 1, 1)
        day = self.rdate(lo, date(2026, 9, 20))
        admit = datetime.combine(day, datetime.min.time()) + timedelta(hours=r.randint(6, 21), minutes=r.randint(0, 59))
        if vt in ("IP", "OBS"):
            disch: datetime | None = admit + timedelta(hours=r.randint(20, 140))
        else:
            disch = admit + timedelta(minutes=r.randint(20, 240)) if r.random() < 0.8 else None
        status = "VOID" if r.random() < 0.02 else "CLOSED"
        lwbs = vt == "ER" and admit.date() >= date(2018, 1, 1) and status == "CLOSED" and r.random() < 0.08
        if lwbs:
            status, disch = "VOID", None
        vno = str(self.nid("visit", 4000000))
        if status == "VOID":
            self.truth["void_kind"][vno] = "lwbs" if lwbs else "error"
            self.issue("lwbs_visit" if lwbs else "void_visit", "VISIT", vno)
        if vt == "IP" and status == "CLOSED" and r.random() < rates["missing_discharge"]:
            disch = None
            self.issue("missing_discharge", "VISIT", vno)
        self.truth["visit_class"][vno] = V.VISIT_TYPES[vt][0]
        self.rows["VISIT"].append({
            "VISIT_NO": vno, "PERSON_NO": chart, "CLINIC_CD": clinic,
            "VISIT_TYPE": vt.lower() if r.random() < 0.01 else vt, "ADMIT_TS": _ts(admit),
            "DISCH_TS": _ts(disch) if disch else "", "STATUS": status, "ATTEND_ID": f"ST{r.randint(1, 18):04d}",
            "CHIEF_COMPLAINT": r.choice(["COUGH", "CHEST PAIN", "FOLLOW UP", "ABD PAIN", "FEVER", "MED REFILL", ""])})
        if status == "CLOSED":
            self.labs(chart, vno, campus, admit)
            if vt != "TH":
                self.vitals(chart, vno, campus, admit)
        elif lwbs:
            self.vitals(chart, vno, campus, admit, triage=True)  # triage vitals before the patient left
        return vno, chart, admit, campus

    def problem(self, chart: str, visits: list[tuple[str, str, datetime, str]]) -> None:
        r = self.rng
        pno = str(self.nid("prob", 600000))
        status = r.choice("AAAIR")
        if r.random() < self.cfg.rates["free_text_dx"]:
            onset = self.rdate(date(2012, 1, 1), date(2026, 6, 1))
            row = {"DX_CODE": "", "CODE_SYS": "", "DX_TEXT": r.choice(V.FREE_TEXT_PROBLEMS)}
            self.truth["dx"][pno] = None
            self.issue("free_text_dx", "PROBLEM", pno)
        else:
            icd10, text, sys_, code = r.choice(V.PROBLEMS)
            onset = self.rdate(date(2008, 1, 1), date(2015, 9, 30)) if sys_ == "I9" else \
                self.rdate(date(2015, 10, 1), date(2026, 6, 1))
            if onset < date(2012, 1, 1):
                code = icd10 if sys_ == "I10" else {"25000": "250.00", "4019": "401.9", "496": "496", "27800": "278.00",
                                                    "71590": "715.90", "311": "311"}[code]
            row = {"DX_CODE": code, "CODE_SYS": sys_, "DX_TEXT": text}
            self.truth["dx"][pno] = icd10
            # Dotless storage and ICD-9 are conventions (graded by value checks), not record problems;
            # only codes that need a human choice are issues.
            if sys_ == "I9" and code in ("311", "71590"):
                self.issue("icd9_one_to_many", "PROBLEM", pno)
            if code == "M545":
                self.issue("retired_icd10", "PROBLEM", pno)
        vis = [v for v in visits if v[1] == chart]
        self.rows["PROBLEM"].append({
            "PROB_NO": pno, "PERSON_NO": chart, "VISIT_NO": r.choice(vis)[0] if vis and r.random() < 0.4 else "", **row,
            "ONSET_DT": _mdy(onset), "RESOLVE_DT": _mdy(onset + timedelta(days=r.randint(30, 900))) if status == "R" else "",
            "STATUS": status})

    def labs(self, chart: str, vno: str, campus: str, admit: datetime) -> None:
        r, rates = self.rng, self.cfg.rates
        if r.random() < 0.45:
            return
        acc = f"{'H' if campus == 'HVMC' else 'S'}{self.nid('acc', 10000000)}"
        when = admit + timedelta(minutes=r.randint(10, 120))
        for code in r.sample(list(V.TESTS), r.randint(1, 4)):
            name, _, _, unit, rng_, ref, kind = V.TESTS[code]
            abn = ""
            if kind == "num":
                lo, hi = rng_
                v = round(r.uniform(lo, hi), 1 if hi < 50 else 0)
                if code == "GLUC" and campus == "SRC":
                    unit, ref = "mmol/L", "3.9-5.5"
                    v = round(v / 18.0, 1)
                result = f"{v:g}"
                try:
                    rlo, rhi = (float(x) for x in ref.split("-")) if "-" in ref else (None, float(ref.strip("<")))
                    abn = "H" if rhi is not None and float(result) > rhi else "L" if rlo is not None and float(result) < rlo else ""
                except ValueError:
                    abn = ""
            elif kind == "posneg":
                result = r.choice(["NEG", "NEG", "NEG", "POS"])
                abn = "A" if result == "POS" else ""
            else:
                result = "SEE SCANNED REPORT"
            status = "F"
            roll = r.random()
            if roll < rates["lab_cancelled"]:
                status = "X"
                result = r.choice(["CANCELLED", result])
            elif roll < rates["lab_cancelled"] + rates["lab_corrected"]:
                status = "C"
            rno = str(self.nid("res", 8000000))
            self.rows["LABRES"].append({
                "RES_NO": rno, "PERSON_NO": chart, "VISIT_NO": vno, "ACCESSION": acc, "TEST_CD": code, "RESULT": result,
                "UNITS": unit, "REF_RANGE": ref, "ABN": abn, "COLLECTED_TS": _ts(when) if campus == "SRC" and when >= datetime(2024, 1, 1) else _oracle_ts(when),
                "RESULT_STATUS": status})
            if status == "X":
                self.truth["lab_cancelled"].append(rno)
                self.issue("cancelled_result", "LABRES", rno)
            if kind == "text" and status != "X":
                self.issue("unmapped_lab", "LABRES", rno)

    def vitals(self, chart: str, vno: str, campus: str, admit: datetime, triage: bool = False) -> None:
        r = self.rng
        migrated = campus == "SRC" and admit.date() < MIGRATION
        metric = campus == "SRC" and not migrated
        when = admit + timedelta(minutes=r.randint(5, 30))
        values = {
            "BP": (f"{r.randint(100, 165)}/{r.randint(60, 98)}", ""),
            "HR": (str(r.randint(55, 115)), ""), "RR": (str(r.randint(12, 24)), ""),
            "TEMP": (f"{r.uniform(36.2, 38.6):.1f}", "C") if metric else (f"{r.uniform(97.2, 101.4):.1f}", ""),
            "WT": (f"{r.uniform(8, 130):.1f}", "kg") if metric else (f"{r.uniform(18, 290):.1f}", ""),
            "HT": (f"{r.uniform(60, 195):.0f}", "cm") if metric else (f"{r.uniform(24, 77):.0f}", ""),
            "SPO2": (str(r.randint(90, 100)), ""),
        }
        for vs in r.sample(V.VITAL_TYPES, r.randint(3, 7)):
            value, unit = values[vs]
            vsno = str(self.nid("vs", 5000000))
            if vs == "TEMP" and not metric and r.random() < self.cfg.rates["implausible_vital"] * 7:
                value = value.replace(".", "")
                self.issue("implausible_vital", "VITALS", vsno)
            if vs in ("TEMP", "WT", "HT") and not metric:
                self.issue("migrated_us_vital" if migrated else "unitless_vital", "VITALS", vsno)
                self.truth["vital_unit"][vsno] = {"TEMP": "[degF]", "WT": "[lb_av]", "HT": "[in_i]"}[vs]
            elif vs in ("TEMP", "WT", "HT"):
                self.truth["vital_unit"][vsno] = {"TEMP": "Cel", "WT": "kg", "HT": "cm"}[vs]
            self.rows["VITALS"].append({"VS_NO": vsno, "PERSON_NO": chart, "VISIT_NO": vno, "TAKEN_TS": _ts(when),
                                        "VS_TYPE": vs, "VS_VALUE": value, "VS_UNIT": unit})


def _write(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    lines = ["|".join(header)] + ["|".join(row[h] for h in header) for row in rows]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))


def generate(out: str | Path, seed: int = 42, patients: int = 300) -> dict[str, Any]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "answer_key").mkdir(exist_ok=True)
    cfg = Config(patients=patients, seed=seed)
    g = Gen(cfg)
    g.reference()
    g.person_rows()
    counts = {}
    for name, header in FILES.items():
        _write(out / f"{name}.DAT", header, g.rows[name])
        counts[name] = len(g.rows[name])
    (out / "MCS2_EXTRACT_GUIDE.TXT").write_bytes(estate.extract_guide().encode("latin-1"))
    (out / "KICKOFF_MEMO.TXT").write_bytes(estate.kickoff_memo().encode("latin-1"))
    manifest = {"system": "Meridian MCS/2", "extract_version": "4.0", "site": V.SYSTEM_NAME, "seed": seed,
                "asOf": cfg.as_of.isoformat(), "counts": counts,
                "notes": {"format": "pipe-delimited, header row, latin-1"}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    key = out / "answer_key"
    (key / "persons.json").write_text(json.dumps(g.persons, indent=1) + "\n")
    (key / "truth.json").write_text(json.dumps(g.truth, indent=1, sort_keys=True) + "\n")
    (key / "issues.jsonl").write_text("".join(json.dumps(i, sort_keys=True) + "\n" for i in g.issues))
    (key / "estate_discrepancies.json").write_text(json.dumps(estate.DISCREPANCIES, indent=1) + "\n")
    return {"out": str(out), "counts": counts, "issues": len(g.issues),
            "persons": len(g.persons), "charts": counts["PERSON"]}
