"""Nimbus import-API client. The only way Bridge talks to Nimbus.

Targets:
  http://host:port     a running Nimbus (`python -m nimbus serve`)
  embedded:<path.db>   dev convenience: starts the Nimbus ASGI app in-process and talks to it over
                       the same HTTP API (via an in-memory transport). Imported dynamically so the
                       Bridge code base has no compile-time dependency on Nimbus internals.
"""
from __future__ import annotations

import importlib
import weakref
from typing import Any

import httpx

MAX_PER_CALL = 500


class TargetError(Exception):
    def __init__(self, status: int, body: Any):
        err = body.get("error", {}) if isinstance(body, dict) else {}
        super().__init__(f"{status}: {err.get('code')} {err.get('message') or body}")
        self.status, self.body, self.code, self.details = status, body, err.get("code"), err.get("details")


class NimbusClient:
    def __init__(self, http: httpx.Client):
        self.http = http

    def _req(self, method: str, url: str, **kw: Any) -> Any:
        r = self.http.request(method, url, **kw)
        body = r.json() if r.content else None
        if r.status_code >= 400:
            raise TargetError(r.status_code, body)
        return body

    def create_batch(self, rtype: str, external_id: str, mode: str = "commit") -> str:
        return self._req("POST", "/api/v1/import/batches", json={
            "resourceType": rtype, "externalBatchId": external_id, "mode": mode, "system": "bridge"})["batchId"]

    def submit(self, batch_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for i in range(0, len(records), MAX_PER_CALL):
            out += self._req("POST", f"/api/v1/import/batches/{batch_id}/records",
                             json={"records": records[i:i + MAX_PER_CALL]})["results"]
        return out

    def close(self, batch_id: str) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/import/batches/{batch_id}/close")

    def rollback(self, batch_id: str, cascade: bool = False) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/import/batches/{batch_id}/rollback", params={"cascade": str(cascade).lower()})

    def count(self, rtype: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/{rtype}/$count")

    def get(self, rtype: str, rid: str) -> dict[str, Any]:
        return self._req("GET", f"/api/v1/{rtype}/{rid}")

    def search(self, rtype: str, **params: Any) -> list[dict[str, Any]]:
        return self._req("GET", f"/api/v1/{rtype}", params=params)["items"]

    def merge(self, target_id: str, source_id: str, batch_id: str | None = None) -> dict[str, Any]:
        return self._req("POST", f"/api/v1/patients/{target_id}/$merge",
                         json={"sourcePatientId": source_id, "importBatchId": batch_id})


def connect(target: str) -> NimbusClient:
    if target.startswith("embedded:"):
        db = target.split(":", 1)[1] or ":memory:"
        api = importlib.import_module("nimbus.api")
        service = importlib.import_module("nimbus.service")
        from fastapi.testclient import TestClient
        # Keep the AnyIO portal alive across embedded requests instead of
        # starting a new portal/thread for each TestClient.request call.
        http = TestClient(api.create_app(service.NimbusService(db)))
        http.__enter__()
        client = NimbusClient(http)
        weakref.finalize(client, http.__exit__, None, None, None)
        return client
    return NimbusClient(httpx.Client(base_url=target, timeout=60))
