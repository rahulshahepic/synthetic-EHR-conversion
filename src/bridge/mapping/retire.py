"""Records converted earlier whose source was deleted since (cutover delta)."""
from __future__ import annotations

from typing import Any, Callable

from .base import MapContext

RETIRE: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "Condition": lambda p: {**p, "verificationStatus": "entered-in-error"},
    "Encounter": lambda p: {**p, "status": "cancelled"},
    "Appointment": lambda p: {**p, "status": "cancelled"},
    "MedicationRequest": lambda p: {**p, "status": "stopped"},
    "Observation": lambda p: {**p, "status": "cancelled"},
}


def map_source_deleted(ctx: MapContext) -> dict[str, Any] | None:
    prior = ctx.src["prior_mapped"]
    options = [{"key": "keep", "label": "Keep them in Nimbus exactly as converted earlier (flagged for review)"}]
    if ctx.rtype in RETIRE:
        options.append({"key": "retire", "label": f"Retire them in Nimbus ({_how(ctx.rtype)})"})
    d = ctx.decide(
        "source_deleted", ctx.rtype,
        f"Some {ctx.rtype} records converted in the prior run ({ctx.src['prior_run']}) no longer exist in the source system "
        "(deleted or purged since). Bridge never deletes clinical data silently. What should happen to them?",
        options, blocking=False, default="keep", context={"resource_type": ctx.rtype, "prior_run": ctx.src["prior_run"]})
    if d["option"] == "retire" and ctx.rtype in RETIRE:
        ctx.note("record", "inferred", 1.0, f"source deleted since prior run; retired ({_how(ctx.rtype)})")
        return RETIRE[ctx.rtype](prior)
    ctx.note("record", "inferred", 1.0, "source deleted since prior run; kept as previously converted")
    return prior


def _how(rtype: str) -> str:
    return {"Condition": "verificationStatus=entered-in-error", "MedicationRequest": "status=stopped"}.get(rtype, "status=cancelled")
