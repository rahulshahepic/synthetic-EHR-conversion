"""Diffing a generated spec against a hand-written control profile.

Used for the Halcyon re-derivation (T-120): the generated profile is
executed into a namespace and compared, fact by fact, with the control
profile's namespace on a defined subset. A fact is:

- ``matched`` — generated value equals the control value;
- ``disputed`` — the interview left the underlying claim unresolved (the
  fact sits in the generated spec's known unknowns, or the constant is
  absent because its dispute never settled);
- ``missed`` — the generated value differs from the control, or the fact
  was never established at all.

Per-facility facts (timezones, vital units) are compared per facility.
Crosswalk coverage compares the generated crosswalks (and documented
gaps) against the control's terminology code sets by name.
"""
from __future__ import annotations

from typing import Any

FACT_SUBJECTS: dict[str, tuple[str, str]] = {
    "SYSTEM_ORG": ("profile", "system_org"),
    "MRN_SYSTEM": ("profile", "mrn_system"),
    "FACILITY_TZ": ("profile", "facility_tz"),
    "VITAL_UNITS": ("profile", "vital_units"),
    "CHARGE_CENTS_FROM": ("profile", "charge_cents_from"),
    "LAB_FEED_ONLY_DAYS": ("profile", "lab_feed_only_days"),
}
PER_FACILITY = {"FACILITY_TZ", "VITAL_UNITS"}


def _is_unknown(spec: dict[str, Any], const: str) -> bool:
    subject = FACT_SUBJECTS[const]
    return any((u.get("subject"), u.get("predicate")) == subject
               for u in spec.get("known_unknowns", []))


def diff_profiles(generated_ns: dict[str, Any], control_ns: dict[str, Any],
                  spec: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for const in sorted(FACT_SUBJECTS):
        control_val = control_ns.get(const)
        gen_val = generated_ns.get(const)
        if const in PER_FACILITY and isinstance(control_val, dict):
            for fac in sorted(control_val):
                g = (gen_val or {}).get(fac)
                status = ("matched" if g == control_val[fac]
                          else "disputed" if _is_unknown(spec, const)
                          else "missed")
                entries.append({"fact": f"{const}[{fac}]", "status": status,
                                "generated": g, "control": control_val[fac]})
            if isinstance(gen_val, dict):
                for fac in sorted(set(gen_val) - set(control_val)):
                    entries.append({"fact": f"{const}[{fac}]",
                                    "status": "extra",
                                    "generated": gen_val[fac],
                                    "control": None})
            continue
        if gen_val is not None and gen_val == control_val:
            status = "matched"
        elif _is_unknown(spec, const):
            status = "disputed"
        else:
            status = "missed"
        entries.append({"fact": const, "status": status,
                        "generated": gen_val, "control": control_val})
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return {"entries": entries, "counts": counts}


def diff_crosswalks(generated: dict[str, str], documented_gaps: set[str],
                    control_sets: list[str]) -> dict[str, Any]:
    covered = sorted(set(generated) & set(control_sets))
    gaps = sorted(set(documented_gaps) & set(control_sets))
    missing = sorted(set(control_sets) - set(generated) - set(documented_gaps))
    return {"covered": covered, "documented_gaps": gaps, "missing": missing,
            "control_total": len(control_sets)}
