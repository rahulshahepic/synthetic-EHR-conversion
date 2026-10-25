"""Late identity merges: two patients already loaded into Nimbus turn out to be one person."""
from __future__ import annotations

from typing import Any

from ..load.client import NimbusClient
from ..runs import store as S


class MergeError(ValueError):
    pass


def merge_loaded_patients(store: S.RunStore, client: NimbusClient, run_id: str, survivor: str, duplicate: str,
                          confirmed_by: str) -> dict[str, Any]:
    surv, dup = store.record(run_id, "Patient", survivor), store.record(run_id, "Patient", duplicate)
    if surv is None or dup is None:
        raise MergeError("both patients must exist in this run")
    if surv["status"] != S.LOADED or dup["status"] != S.LOADED:
        raise MergeError(f"both patients must be loaded (survivor {surv['status']}, duplicate {dup['status']}); "
                         "for unloaded charts answer the identity question instead")
    bridge_batch = store.create_batch(run_id, "Patient", "")
    nimbus_batch = client.create_batch("Patient", bridge_batch)
    store.db.execute("UPDATE batches SET nimbus_batch_id=? WHERE id=?", (nimbus_batch, bridge_batch))
    res = client.merge(surv["target_id"], dup["target_id"], nimbus_batch)
    client.close(nimbus_batch)

    members = [m["PAT_ID"] for m in dup["source"]["members"]]
    undo = {"survivor": survivor, "duplicate": duplicate, "members": members,
            "survivor_source": surv["source"], "duplicate_target_id": dup["target_id"], "duplicate_batch": dup["batch_id"]}
    with store.tx():
        src = surv["source"]
        src["members"] += dup["source"]["members"]
        src["links"].update({m: f"late-merge by {confirmed_by}" for m in members})
        store.update_record(run_id, "Patient", survivor, source=src)
        store.update_record(run_id, "Patient", duplicate, status=S.SUPERSEDED, note=f"merged into {survivor} by {confirmed_by}")
        store.xset(run_id, "superseded", f"Patient/{duplicate}", survivor)
        for m in members:
            store.xset(run_id, "pat", m, survivor)
        store.xset(run_id, "merge_batch", bridge_batch, undo)
    store.finish_batch(bridge_batch, "loaded", {"attempted": 1, "loaded": 1}, {"merge": res})
    store.event(run_id, "late_merge", {"survivor": survivor, "duplicate": duplicate, "by": confirmed_by,
                                       "batch": bridge_batch, "moved_references": res.get("movedReferences")})
    return {"batch": bridge_batch, **res}


def undo_merge_bookkeeping(store: S.RunStore, run_id: str, batch_id: str) -> None:
    """Called after Nimbus rolled back a merge batch: restore Bridge's view."""
    undo = store.xget(run_id, "merge_batch", batch_id)
    if not undo:
        return
    store.update_record(run_id, "Patient", undo["survivor"], source=undo["survivor_source"])
    store.update_record(run_id, "Patient", undo["duplicate"], status=S.LOADED, note="late merge reverted",
                        target_id=undo["duplicate_target_id"], batch_id=undo["duplicate_batch"])
    store.db.execute("DELETE FROM xref WHERE run_id=? AND kind='superseded' AND key=?", (run_id, f"Patient/{undo['duplicate']}"))
    store._pat_ids.clear()  # patient_pat_ids cache: the merge link is gone
    for m in undo["members"]:
        store.xset(run_id, "pat", m, undo["duplicate"])
    store.db.execute("DELETE FROM xref WHERE run_id=? AND kind='merge_batch' AND key=?", (run_id, batch_id))
