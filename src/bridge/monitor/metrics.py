"""Per-batch metrics."""
from __future__ import annotations

from collections import Counter
from typing import Any

CODE_FIELDS = {"code", "substance", "medication", "vaccine", "specialty"}
GOOD_CODE = {"exact", "transformed", "standardized", "inferred"}


def batch_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """`results`: one dict per attempted record with keys status, fidelity, issues, annotations, source_key."""
    st = Counter(r["status"] for r in results)
    attempted = len(results)
    submitted = st["loaded"] + st["rejected"]
    loaded = [r for r in results if r["status"] == "loaded"]
    fid = [r["fidelity"] for r in loaded if r.get("fidelity") is not None]
    issue_codes = Counter(i["code"] for r in results for i in (r.get("issues") or []) if i.get("severity") == "error")
    loss = Counter()
    coded_total = coded_good = 0
    for r in loaded:
        for a in r.get("annotations") or []:
            if a["klass"] in ("inferred", "degraded", "defaulted", "dropped"):
                loss[f"{a['field'].split('.')[0]}:{a['klass']}"] += 1
            if a["field"] in CODE_FIELDS:
                coded_total += 1
                coded_good += a["klass"] in GOOD_CODE
    return {
        "attempted": attempted,
        **{k: st[k] for k in ("loaded", "rejected", "held", "blocked", "dropped", "superseded")},
        "unchanged": sum(1 for r in loaded if r.get("unchanged")),
        "target_reject_rate": round(st["rejected"] / submitted, 4) if submitted else 0.0,
        "hold_rate": round(st["held"] / attempted, 4) if attempted else 0.0,
        "fidelity_mean": round(sum(fid) / len(fid), 4) if fid else None,
        "low_fidelity_share": round(sum(1 for f in fid if f < 0.7) / len(fid), 4) if fid else 0.0,
        "code_coverage": round(coded_good / coded_total, 4) if coded_total else None,
        "ref_unresolved": issue_codes.get("E_REF_UNRESOLVED", 0),
        "funnel_ok": attempted == sum(st.values()),
        "issue_codes": dict(issue_codes),
        "loss_top": dict(loss.most_common(8)),
    }
