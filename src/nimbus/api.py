"""Nimbus REST API v1 (FastAPI) over NimbusService."""
from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from . import models as m
from .service import NimbusError, NimbusService
from .valuesets import VALUESETS


def create_app(service: NimbusService | None = None) -> FastAPI:
    svc = service or NimbusService()
    app = FastAPI(title="Nimbus EHR", version="1.0")
    app.state.service = svc

    @app.exception_handler(NimbusError)
    async def _nimbus_error(_: Request, exc: NimbusError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.to_dict()})

    @app.get("/api/v1/meta/schema")
    def schema() -> dict[str, Any]:
        return {name: cls.model_json_schema(by_alias=True) for name, cls in m.RESOURCE_MODELS.items()}

    @app.get("/api/v1/meta/valuesets/{name}")
    def valueset(name: str) -> dict[str, Any]:
        if name not in VALUESETS:
            raise NimbusError("E_NOT_FOUND", f"valueset {name} not found")
        return {"name": name, "values": VALUESETS[name]}

    @app.post("/api/v1/import/batches", status_code=201)
    def create_batch(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return svc.create_batch(body.get("resourceType", ""), body.get("externalBatchId"),
                                body.get("mode", "commit"), body.get("system"))

    @app.get("/api/v1/import/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        return svc.get_batch(batch_id)

    @app.post("/api/v1/import/batches/{batch_id}/records")
    def submit(batch_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return svc.submit_records(batch_id, body.get("records", []))

    @app.post("/api/v1/import/batches/{batch_id}/close")
    def close(batch_id: str) -> dict[str, Any]:
        return svc.close_batch(batch_id)

    @app.post("/api/v1/import/batches/{batch_id}/rollback")
    def rollback(batch_id: str, cascade: bool = False) -> dict[str, Any]:
        return svc.rollback_batch(batch_id, cascade=cascade)

    @app.post("/api/v1/patients/{patient_id}/$merge")
    def merge(patient_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return svc.merge_patients(patient_id, body.get("sourcePatientId", ""), body.get("importBatchId"))

    @app.get("/api/v1/{resource_type}/$count")
    def count(resource_type: str) -> dict[str, Any]:
        return svc.count(resource_type)

    @app.get("/api/v1/{resource_type}/{rid}")
    def read(resource_type: str, rid: str) -> dict[str, Any]:
        return svc.get(resource_type, rid)

    @app.get("/api/v1/{resource_type}")
    def search(resource_type: str, sourceKey: str | None = None, identifier: str | None = None,
               patient: str | None = None, limit: int = 100, offset: int = 0,
               afterCreatedAt: str | None = None, afterId: str | None = None) -> dict[str, Any]:
        items = svc.search(resource_type, sourceKey, identifier, patient, min(limit, 1000), offset, afterCreatedAt, afterId)
        return {"resourceType": resource_type, "items": items}

    return app
