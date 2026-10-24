"""Carry answered mapping rules between runs (rehearsal 1 -> rehearsal 2 -> cutover)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..runs import store as S
from .answers import _merge_identity

FORMAT = "bridge-rules/1"


def export_rules(store: S.RunStore, run_id: str) -> dict[str, Any]:
    return {"format": FORMAT, "source_run": run_id, "rules": [
        {"kind": r["kind"], "match_key": r["match_key"], "decision": r["decision"], "created_by": r["created_by"],
         "created_at": r["created_at"]} for r in store.rules(run_id)]}


def load_rules(path_or_db: str) -> list[dict[str, Any]]:
    """Read rules from an exported JSON file or directly from a prior run DB (latest run)."""
    p = Path(path_or_db)
    if p.suffix == ".json":
        data = json.loads(p.read_text())
        if data.get("format") != FORMAT:
            raise ValueError(f"{p} is not a {FORMAT} file")
        return [{**r, "source_run": data.get("source_run")} for r in data["rules"]]
    other = S.RunStore(str(p))
    run = other.run()
    return [{**r, "source_run": run["id"]} for r in export_rules(other, run["id"])["rules"]]


def import_rules(store: S.RunStore, run_id: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
    imported = merges = 0
    for r in rules:
        store.add_rule(run_id, r["kind"], r["match_key"], r["decision"],
                       f"import:{r.get('source_run', '?')}:{r['created_by']}")
        imported += 1
        if r["kind"] == "identity_match" and r["decision"].get("option") == "same":
            a, _, b = r["match_key"].partition("|")
            if store.status_of(run_id, "Patient", a) and store.status_of(run_id, "Patient", b) == S.PENDING:
                _merge_identity(store, run_id, {"context": {"candidate_patient": a, "this_patient": b}})
                merges += 1
    store.event(run_id, "rules_imported", {"rules": imported, "identity_merges": merges})
    return {"imported": imported, "identity_merges": merges}
