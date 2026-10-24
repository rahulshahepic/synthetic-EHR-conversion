"""End-of-run verification: count reconciliation, read-back sampling, clinical sentinels.

Every check compares what Bridge believed it sent against what Nimbus actually holds, and every
source-vs-target difference must be explained by a record-level status (held, dropped, ...).
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Any, Callable

from .load.client import NimbusClient
from .runs import store as S
from .terminology import TERMS

ANTICOAG_RXNORM = {"855332", "1364445"}
INSULIN_RXNORM = {"285018"}


# ----------------------------------------------------------------------------- counts
def count_reconciliation(store: S.RunStore, client: NimbusClient, run_id: str) -> dict[str, Any]:
    out, ok = {}, True
    for rtype, counts in store.status_counts(run_id).items():
        staged = sum(counts.values())
        nimbus = client.count(rtype)["total"]
        loaded = counts.get(S.LOADED, 0)
        row = {"staged": staged, **counts, "nimbus": nimbus, "nimbus_matches_loaded": nimbus == loaded,
               "funnel_closed": staged == sum(counts.get(k, 0) for k in (S.LOADED, S.DROPPED, S.SUPERSEDED, S.HELD,
                                                                           S.BLOCKED, S.REJECTED, S.PENDING))}
        ok &= row["nimbus_matches_loaded"] and row["funnel_closed"]
        out[rtype] = row
    return {"ok": ok, "by_type": out}


# ----------------------------------------------------------------------------- read-back
def _same(sent: Any, got: Any) -> bool:
    if isinstance(sent, dict) and "sourceKey" in sent and set(sent) <= {"sourceKey", "id"}:
        return isinstance(got, dict) and got.get("sourceKey") == sent["sourceKey"]
    if isinstance(sent, dict):
        return isinstance(got, dict) and all(_same(v, got.get(k)) for k, v in sent.items() if v is not None)
    if isinstance(sent, list):
        return isinstance(got, list) and len(sent) == len(got) and all(_same(a, b) for a, b in zip(sent, got))
    if isinstance(sent, float) or isinstance(got, float):
        try:
            return abs(float(sent) - float(got)) < 1e-9
        except (TypeError, ValueError):
            return False
    return sent == got


def readback(store: S.RunStore, client: NimbusClient, run_id: str, per_type: int = 25, seed: int = 0) -> dict[str, Any]:
    rng = random.Random(seed)
    result, mismatches = {}, []
    for rtype in store.status_counts(run_id):
        recs = store.records_by_status(run_id, S.LOADED, rtype, limit=1_000_000)
        sample = rng.sample(recs, min(per_type, len(recs)))
        bad = 0
        for r in sample:
            got = client.get(rtype, r["target_id"])
            diffs = [k for k, v in (r["mapped"] or {}).items() if v is not None and not _same(v, got.get(k))]
            if got.get("sourceKey") != r["source_key"]:
                diffs.append("sourceKey")
            if diffs:
                bad += 1
                mismatches.append({"rtype": rtype, "source_key": r["source_key"], "fields": diffs})
        result[rtype] = {"sampled": len(sample), "mismatched": bad}
    total = sum(v["sampled"] for v in result.values())
    bad = sum(v["mismatched"] for v in result.values())
    return {"ok": bad == 0, "sampled": total, "mismatch_rate": round(bad / total, 4) if total else 0.0,
            "by_type": result, "mismatches": mismatches[:20]}


# ----------------------------------------------------------------------------- sentinels
def _source_records(store: S.RunStore, run_id: str, rtype: str) -> list[dict[str, Any]]:
    return [store._rec(r) for r in store.db.execute("SELECT * FROM records WHERE run_id=? AND rtype=?", (run_id, rtype))]


def _nimbus_all(client: NimbusClient, rtype: str) -> list[dict[str, Any]]:
    out, offset = [], 0
    while True:
        page = client.search(rtype, limit=1000, offset=offset)
        out += page
        if len(page) < 1000:
            return out
        offset += 1000


def _sentinel(name: str, description: str, source: list[dict[str, Any]], keep: Callable[[dict[str, Any]], bool],
              nimbus_count: int, unit: Callable[[dict[str, Any]], str] = lambda r: r["source_key"]) -> dict[str, Any]:
    """Source items matching `keep`; every one must be in Nimbus or explained by a record status."""
    items = [r for r in source if keep(r)]
    by_status = Counter(r["status"] for r in items)
    units_loaded = {unit(r) for r in items if r["status"] == S.LOADED}
    explained = {s: n for s, n in by_status.items() if s != S.LOADED}
    expected = len(units_loaded)
    unexplained = nimbus_count - expected
    return {"name": name, "description": description, "source": len({unit(r) for r in items}),
            "expected_in_nimbus": expected, "nimbus": nimbus_count, "not_loaded_by_status": explained,
            "unexplained_delta": unexplained, "ok": unexplained == 0,
            "not_loaded_examples": [r["source_key"] for r in items if r["status"] != S.LOADED][:10]}


def sentinels(store: S.RunStore, client: NimbusClient, run_id: str) -> dict[str, Any]:
    pat_of = store.xall(run_id, "pat")
    meds = _source_records(store, run_id, "MedicationRequest")
    n_meds = _nimbus_all(client, "MedicationRequest")

    def active_with(codes: set[str]) -> Callable[[dict[str, Any]], bool]:
        return lambda r: r["source"]["STATUS"] == "A" and TERMS.formulary.get(r["source"]["FORM_CODE"], ("",))[0] in codes

    def nimbus_active(codes: set[str]) -> int:
        return sum(1 for m in n_meds if m["status"] == "active"
                   and any(c["code"] in codes for c in m["medication"].get("coding", [])))

    allergies = _source_records(store, run_id, "AllergyIntolerance")
    n_alg = _nimbus_all(client, "AllergyIntolerance")
    labs = _source_records(store, run_id, "Observation")
    n_obs = _nimbus_all(client, "Observation")
    checks = [
        _sentinel("active_anticoagulants", "Active warfarin/apixaban orders", meds, active_with(ANTICOAG_RXNORM),
                  nimbus_active(ANTICOAG_RXNORM)),
        _sentinel("active_insulin", "Active insulin orders", meds, active_with(INSULIN_RXNORM), nimbus_active(INSULIN_RXNORM)),
        _sentinel("patients_with_allergies", "Distinct patients with at least one real allergy",
                  allergies, lambda r: r["source"]["ALLERGEN"].strip().upper() not in ("NKA", "NKDA"),
                  len({a["patient"]["id"] for a in n_alg}),
                  unit=lambda r: _resolve_patient(store, run_id, pat_of.get(r["source"]["PAT_ID"]))),
        _sentinel("abnormal_labs", "Lab results flagged abnormal (H/L/A)", labs,
                  lambda r: r["source"].get("kind") == "lab" and r["source"].get("ABN_FLAG", "").strip() in ("H", "L", "A"),
                  sum(1 for o in n_obs if o.get("category") == "laboratory" and o.get("interpretation") in ("high", "low", "abnormal"))),
    ]
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _resolve_patient(store: S.RunStore, run_id: str, key: str | None) -> str:
    seen = set()
    while key and key not in seen and store.status_of(run_id, "Patient", key) == S.SUPERSEDED:
        seen.add(key)
        key = store.xget(run_id, "superseded", f"Patient/{key}")
    return key or "?"


# ----------------------------------------------------------------------------- orchestration
def verify_run(store: S.RunStore, client: NimbusClient, run_id: str, readback_per_type: int = 25) -> dict[str, Any]:
    report = {"counts": count_reconciliation(store, client, run_id),
              "readback": readback(store, client, run_id, readback_per_type),
              "sentinels": sentinels(store, client, run_id)}
    report["ok"] = all(report[k]["ok"] for k in ("counts", "readback", "sentinels"))
    store.event(run_id, "verification", {"ok": report["ok"], "counts_ok": report["counts"]["ok"],
                                         "readback_mismatch_rate": report["readback"]["mismatch_rate"],
                                         "sentinels": {c["name"]: c["ok"] for c in report["sentinels"]["checks"]}})
    for c in report["sentinels"]["checks"]:
        if not c["ok"]:
            store.add_alert(run_id, rule="clinical_sentinel", metric=c["name"], observed=c["nimbus"],
                            threshold=c["expected_in_nimbus"], severity="pause", rtype=None,
                            message=f"Clinical sentinel {c['name']}: Nimbus has {c['nimbus']}, expected {c['expected_in_nimbus']} "
                                    f"(unexplained delta {c['unexplained_delta']})", samples=c["not_loaded_examples"],
                            suggested=["investigate before go-live; do not acknowledge without clinical sign-off"])
    if not report["counts"]["ok"]:
        store.add_alert(run_id, rule="count_reconciliation", metric="nimbus_vs_loaded", severity="pause",
                        message="Nimbus counts do not match Bridge's loaded records", samples=[
                            t for t, v in report["counts"]["by_type"].items() if not (v["nimbus_matches_loaded"] and v["funnel_closed"])])
    if not report["readback"]["ok"]:
        store.add_alert(run_id, rule="readback", metric="readback_mismatch_rate", observed=report["readback"]["mismatch_rate"],
                        threshold=0, severity="pause", message="Nimbus returned data different from what Bridge sent",
                        samples=report["readback"]["mismatches"][:10])
    return report
