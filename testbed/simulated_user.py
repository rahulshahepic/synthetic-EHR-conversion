"""A simulated conversion analyst who answers Bridge's questions using the Halcyon answer key.

Test/demo fixture only: it reads ground truth that Bridge itself never sees, so it plays the role of
a knowledgeable human (HIM analyst, clinician) answering reconciliation questions correctly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SimulatedAnalyst:
    name = "user:sim-analyst"

    def __init__(self, export_dir: str | Path):
        key = Path(export_dir) / "answer_key"
        self.persons: dict[str, list[str]] = json.loads((key / "persons.json").read_text())
        self.truth: dict[str, dict[str, Any]] = json.loads((key / "truth.json").read_text())
        self.person_of = {pat: person for person, pats in self.persons.items() for pat in pats}

    def choose(self, q: dict[str, Any], example_source: dict[str, Any] | None) -> tuple[str, str | None, str]:
        """Return (option, value, rationale) for a question (as returned by BridgeAssistant.get_question)."""
        keys = {o["key"] for o in q["options"]}
        kind = q["kind"]
        if kind == "identity_match":
            a, b = (c["PAT_ID"] for c in q["context"]["charts"])
            same = self.person_of.get(a) == self.person_of.get(b)
            return ("same" if same else "different"), None, "registration records confirm" + ("" if same else " different people")
        if kind in ("icd9_one_to_many", "retired_icd10", "unmapped_icd9", "unmapped_local_dx") and example_source:
            code = self.truth.get("dx", {}).get(example_source.get("DX_ID", ""))
            if code in keys:
                return code, None, "chart review"
            if code:
                return "other", code, "chart review"
            return "text", None, "no reliable code"
        if kind == "missing_birth_date" and example_source:
            pat = example_source.get("primary")
            dob = self.truth.get("person", {}).get(self.person_of.get(pat, ""), {}).get("dob")
            if dob:
                return "value", dob, "verified with patient registration"
            return "placeholder", None, "registration follow-up"
        preferred = {"shared_department": "duplicate", "unknown_visit_type": "ambulatory",
                     "missing_discharge": "unknown_end", "unmapped_medication": "exclude", "unmapped_lab": "exclude"}
        opt = preferred.get(kind)
        if opt in keys:
            return opt, None, "department policy"
        return q["options"][0]["key"], None, "accepting Bridge's recommendation"
