"""Export mutator (T-111): produce export B = "the same Halcyon system some weeks later" from export A.

Every primary key in A stays stable in B except listed deletions. B gets new patients with charts, new visits
(with vitals and notes) for existing patients, new lab results (in the ORU feed only, per Halcyon's "last 30 days
only in feed" rule), demographic changes (DB row + ADT A08), status changes (meds discontinued, appointments
completed/cancelled) and a few deletions (entered-in-error problems, purged cancelled appointments).
`answer_key/delta.json` lists every change by table. Deterministic for a seed. Test/demo fixture only.

    python -m testbed.halcyon mutate --from exports/a --out exports/b --seed 7 [--weeks 6]
"""
from __future__ import annotations

import json
import random
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import vocab as V

PKS = {"FACILITY": "FAC_ID", "DEPT": "DEPT_ID", "PROVIDER": "PROV_ID", "PAT": "PAT_ID", "PAT_ALIAS": "ALIAS_ID",
       "VISIT": "VISIT_ID", "DX": "DX_ID", "MED_ORD": "ORD_ID", "ALLERGY": "ALG_ID", "LAB_RESULT": "RES_ID",
       "VITALS": "VITAL_ID", "NOTE": "NOTE_ID", "IMMUN": "IMM_ID", "SCHED": "APPT_ID", "PAYER": "PAYER_ID",
       "PLAN": "PLAN_ID", "COVERAGE": "COV_ID", "CHARGE": "CHG_ID", "USERS": "USER_ID"}


def _d8(d: date) -> str:
    return d.strftime("%Y%m%d")


def _dt12(d: datetime) -> str:
    return d.strftime("%Y%m%d%H%M")


def _esc(s: str) -> str:
    return s.replace("\\", "\\E\\").replace("|", "\\F\\").replace("^", "\\S\\").replace("~", "\\R\\").replace("&", "\\T\\")


class Mutator:
    def __init__(self, src: Path, out: Path, seed: int, weeks: int):
        self.src, self.out, self.r = src, out, random.Random(seed)
        self.manifest = json.loads((src / "manifest.json").read_text())
        self.as_of_a = date.fromisoformat(self.manifest["asOf"])
        self.as_of_b = self.as_of_a + timedelta(weeks=weeks)
        self.delta: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"added": [], "changed": [], "deleted": []})
        self.feeds: dict[str, list[str]] = defaultdict(list)
        self.feed_keys: dict[str, list[str]] = defaultdict(list)
        self._msg = 0

    # ------------------------------------------------------------------ helpers
    def next_id(self, table: str) -> str:
        pk = PKS[table]
        ids = [r[0] for r in self.db.execute(f"SELECT {pk} FROM {table}")]
        prefix = re.match(r"[A-Z]+", ids[0]).group(0) if ids else table[:2]
        width = len(ids[0]) - len(prefix) if ids else 6
        n = max((int(i[len(prefix):]) for i in ids if i.startswith(prefix) and i[len(prefix):].isdigit()), default=0) + 1
        return f"{prefix}{n:0{width}d}"

    def insert(self, table: str, row: dict[str, str]) -> None:
        cols = list(row)
        self.db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
        self.delta[table]["added"].append(row[PKS[table]])

    def update(self, table: str, key: str, **fields: str) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE {table} SET {sets} WHERE {PKS[table]}=?", [*fields.values(), key])
        if key not in self.delta[table]["changed"]:
            self.delta[table]["changed"].append(key)

    def delete(self, table: str, key: str) -> None:
        self.db.execute(f"DELETE FROM {table} WHERE {PKS[table]}=?", (key,))
        self.delta[table]["deleted"].append(key)

    def rows(self, sql: str, args: tuple = ()) -> list[dict[str, str]]:
        return [dict(r) for r in self.db.execute(sql, args)]

    def when(self, hours: tuple[int, int] = (8, 17)) -> datetime:
        d = self.as_of_a + timedelta(days=self.r.randint(1, (self.as_of_b - self.as_of_a).days))
        return datetime(d.year, d.month, d.day, self.r.randint(*hours), self.r.choice([0, 15, 30, 45]))

    def msh(self, mtype: str, when: datetime) -> str:
        self._msg += 1
        return f"MSH|^~\\&|HALCYON|CUTOVER|BRIDGE|NIMBUS|{_dt12(when)}||{mtype}|MUT{self._msg:07d}|P|2.3"

    def pid(self, p: dict[str, str]) -> str:
        last, _, rest = p["PAT_NAME"].partition(",")
        first, _, middle = rest.partition(" ")
        addr = (p["ADDR"].split("^") + [""] * 5)[:5] if "^" in p["ADDR"] else [p["ADDR"], "", "", "", ""]
        return (f"PID|1||{p['MRN']}^^^{p['FAC_ID']}^MR||{_esc(last)}^{_esc(first)}^{_esc(middle)}||{p['DOB']}|{p['SEX']}|||"
                + "^".join(_esc(a) for a in addr) + f"||{_esc(p['PHONE_HOME'])}|||||||{p['SSN4']}")

    def phone(self) -> str:
        return f"({self.r.randint(201, 989)}) {self.r.randint(200, 999)}-{self.r.randint(0, 9999):04d}"

    def address(self) -> str:
        city, state, zip3 = self.r.choice(V.CITIES)
        return f"{self.r.randint(10, 9999)} {self.r.choice(V.STREETS)}^^{city}^{state}^{zip3}{self.r.randint(10, 99)}"

    # ------------------------------------------------------------------ run
    def run(self) -> dict[str, Any]:
        if self.out.exists():
            shutil.rmtree(self.out)
        shutil.copytree(self.src, self.out)
        self.db = sqlite3.connect(self.out / "halcyon.db")
        self.db.row_factory = sqlite3.Row
        pats = self.rows("SELECT * FROM PAT ORDER BY PAT_ID")
        self.providers = [r["PROV_ID"] for r in self.rows("SELECT PROV_ID FROM PROVIDER WHERE ACTIVE='Y' ORDER BY PROV_ID")]
        self.clinics = defaultdict(list)
        for d in self.rows("SELECT * FROM DEPT ORDER BY DEPT_ID"):
            if d["DEPT_KIND"] == "clinic" and d["FAC_ID"]:
                self.clinics[d["FAC_ID"]].append(d["DEPT_ID"])
        self.new_persons: dict[str, list[str]] = {}

        for _ in range(max(2, len(pats) // 30)):
            self.new_patient()
        for p in self.r.sample(pats, max(3, len(pats) // 10)):
            self.new_visit(p)
        for p in self.r.sample(pats, max(2, len(pats) // 20)):
            self.demographic_change(p)
        self.status_changes()
        self.deletions()
        self.db.commit()
        self.db.close()
        return self.write_outputs()

    def new_patient(self) -> None:
        r = self.r
        fac = r.choice(sorted(self.clinics))
        n = max((int(m[0][1:]) for m in self.db.execute("SELECT MRN FROM PAT WHERE FAC_ID=?", (fac,)) if m[0][1:].isdigit()), default=0)
        mrn = f"{fac[-1]}{n + 1:07d}"
        sex = r.choice("FM")
        first = r.choice(V.FIRST_NAMES_F if sex == "F" else V.FIRST_NAMES_M)
        last = r.choice(V.LAST_NAMES)
        dob = date(r.randint(1940, 2020), r.randint(1, 12), r.randint(1, 28))
        pat_id = self.next_id("PAT")
        row = {"PAT_ID": pat_id, "MRN": mrn, "FAC_ID": fac, "PAT_NAME": f"{last.upper()},{first.upper()}", "DOB": _d8(dob),
               "SEX": sex, "RACE": r.choice(["WHITE", "BLACK", "ASIAN", "Hispanic", "DECLINED"]), "ADDR": self.address(),
               "PHONE_HOME": self.phone(), "PHONE_CELL": "", "SSN4": f"{r.randint(0, 9999):04d}", "DECEASED_DT": "",
               "NKA_FLAG": "Y", "LAST_UPD": _d8(self.as_of_a + timedelta(days=1))}
        self.insert("PAT", row)
        self.new_persons[f"NEW-{pat_id}"] = [pat_id]
        when = datetime.combine(self.as_of_a + timedelta(days=1), datetime.min.time()) + timedelta(hours=9)
        self.feeds["adt"].append("\r".join([self.msh("ADT^A04", when), f"EVN|A04|{_dt12(when)}", self.pid(row), f"PV1|1|O|{fac}"]))
        self.feed_keys["adt"].append(f"A04:{pat_id}")
        for _ in range(r.randint(1, 2)):
            self.new_visit(row)

    def new_visit(self, p: dict[str, str]) -> None:
        r = self.r
        if p["DECEASED_DT"]:
            return
        vid = self.next_id("VISIT")
        admit = self.when()
        prov = r.choice(self.providers)
        self.insert("VISIT", {"VISIT_ID": vid, "PAT_ID": p["PAT_ID"], "VISIT_TYPE": "OV", "ADMIT_DT": _dt12(admit), "DISCH_DT": "",
                              "DEPT_ID": r.choice(self.clinics.get(p["FAC_ID"]) or ["D200"]), "ATTEND_PROV_ID": prov,
                              "REASON_TEXT": r.choice(["f/u", "med refill", "cough"]), "STATUS": "C"})
        wt_lb = p["FAC_ID"] != "FAC3"
        kg = r.uniform(40, 110)
        self.insert("VITALS", {"VITAL_ID": self.next_id("VITALS"), "PAT_ID": p["PAT_ID"], "VISIT_ID": vid, "TAKEN_DT": _dt12(admit),
                               "BP": f"{r.randint(100, 160)}/{r.randint(60, 95)}", "PULSE": str(r.randint(55, 100)),
                               "RESP": str(r.randint(12, 20)), "TEMP": "98.4" if wt_lb else "36.9",
                               "WT": f"{kg * 2.20462:.1f}" if wt_lb else f"{kg:.1f}", "HT": "", "SPO2": str(r.randint(94, 100))})
        if r.random() < 0.6:
            self.insert("NOTE", {"NOTE_ID": self.next_id("NOTE"), "PAT_ID": p["PAT_ID"], "VISIT_ID": vid, "AUTHOR_PROV_ID": prov,
                                 "NOTE_TYPE": "PN", "NOTE_DT": _dt12(admit),
                                 "NOTE_TEXT": r"{\rtf1\ansi {\b SUBJECTIVE:}\par Follow-up after cutover window.\par}"})
        if r.random() < 0.5:
            self.new_labs(p, admit)

    def new_labs(self, p: dict[str, str], admit: datetime) -> None:
        r = self.r
        acc = f"M{len(self.feed_keys['oru']) + 1:08d}"
        collect = admit + timedelta(minutes=30)
        segs = [self.msh("ORU^R01", collect + timedelta(hours=2)), self.pid(p), f"OBR|1||{acc}|PANEL^LAB PANEL^L|||{_dt12(collect)}"]
        for i, code in enumerate(r.sample(["GLU", "K", "NA", "HGBA1C", "CREAT"], 2), 1):
            desc, _, unit, _, normal, typical = V.LABS[code]
            val = round(r.uniform(*typical), 1)
            flag = "H" if val > normal[1] else "L" if val < normal[0] else ""
            segs.append(f"OBX|{i}|NM|{code}^{desc}^L||{val:g}|{unit}|{normal[0]:g}-{normal[1]:g}|{flag}|||F|||{_dt12(collect)}")
            self.feed_keys["oru"].append(f"{acc}:{code}")
        self.feeds["oru"].append("\r".join(segs))

    def demographic_change(self, p: dict[str, str]) -> None:
        if p["PAT_ID"] in self.delta["PAT"]["added"]:
            return
        when = self.when((9, 16))
        new = {"ADDR": self.address(), "PHONE_HOME": self.phone(), "LAST_UPD": _d8(when.date())}
        self.update("PAT", p["PAT_ID"], **new)
        row = {**p, **new}
        self.feeds["adt"].append("\r".join([self.msh("ADT^A08", when), f"EVN|A08|{_dt12(when)}", self.pid(row), f"PV1|1|O|{p['FAC_ID']}"]))
        self.feed_keys["adt"].append(f"A08:{p['PAT_ID']}")

    def status_changes(self) -> None:
        active = self.rows("SELECT ORD_ID FROM MED_ORD WHERE STATUS='A' ORDER BY ORD_ID")
        for o in self.r.sample(active, min(len(active), max(1, len(active) // 20))):
            self.update("MED_ORD", o["ORD_ID"], STATUS="D", STOP_DT=_d8(self.when().date()))
        booked = self.rows("SELECT APPT_ID, APPT_DT FROM SCHED WHERE STATUS='S' ORDER BY APPT_ID")
        for a in booked:
            if a["APPT_DT"][:8] <= _d8(self.as_of_b) and self.r.random() < 0.6:
                self.update("SCHED", a["APPT_ID"], STATUS=self.r.choice(["C", "C", "C", "N", "X"]))

    def deletions(self) -> None:
        dx = self.rows("SELECT DX_ID FROM DX WHERE CODE_TYPE='10' ORDER BY DX_ID")
        for d in self.r.sample(dx, min(len(dx), max(1, len(dx) // 100))):
            self.delete("DX", d["DX_ID"])
        cancelled = self.rows("SELECT APPT_ID FROM SCHED WHERE STATUS='X' ORDER BY APPT_ID")
        for a in self.r.sample(cancelled, min(len(cancelled), max(1, len(cancelled) // 10))):
            if a["APPT_ID"] not in self.delta["SCHED"]["changed"]:
                self.delete("SCHED", a["APPT_ID"])

    # ------------------------------------------------------------------ outputs
    def write_outputs(self) -> dict[str, Any]:
        for kind, msgs in self.feeds.items():
            path = self.out / "feeds" / f"{kind}_0001.hl7"
            with open(path, "ab") as f:
                f.write(("\n" + "\n\n".join(msgs) + "\n").encode("latin-1", errors="replace"))
        key = self.out / "answer_key"
        persons = json.loads((key / "persons.json").read_text())
        persons.update(self.new_persons)
        (key / "persons.json").write_text(json.dumps(persons, indent=1))
        delta = {"from_export": str(self.src), "as_of_a": self.as_of_a.isoformat(), "as_of_b": self.as_of_b.isoformat(),
                 "tables": {t: v for t, v in sorted(self.delta.items())}, "feeds": dict(self.feed_keys)}
        (key / "delta.json").write_text(json.dumps(delta, indent=1))
        self.manifest["asOf"] = self.as_of_b.isoformat()
        self.manifest["derivedFrom"] = {"asOf": self.as_of_a.isoformat(), "mutation": "T-111"}
        (self.out / "manifest.json").write_text(json.dumps(self.manifest, indent=1))
        return {"as_of_b": self.as_of_b.isoformat(),
                "tables": {t: {k: len(v) for k, v in d.items()} for t, d in delta["tables"].items()},
                "feeds": {k: len(v) for k, v in self.feed_keys.items()}}


def mutate(src: Path | str, out: Path | str, seed: int = 1, weeks: int = 6) -> dict[str, Any]:
    return Mutator(Path(src), Path(out), seed, weeks).run()
